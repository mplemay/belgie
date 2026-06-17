use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use deno_core::anyhow::{Context, anyhow};
use deno_core::error::AnyError;
use tempfile::TempDir;

use crate::embed::{EmbedContext, EmbedContextOptions, install_packages_with_options};
use crate::packages::{
    PackageDependency, dependencies_from_folder, dependencies_from_mapping, write_synthetic_config,
};

#[derive(Clone, Debug)]
pub(crate) struct EnvironmentDefinition {
    cwd: PathBuf,
    dependencies: Vec<PackageDependency>,
    lockfile_source: Option<PathBuf>,
}

#[derive(Clone)]
pub(crate) struct SharedEnvironment {
    definition: Arc<EnvironmentDefinition>,
    state: Arc<Mutex<EnvironmentState>>,
}

#[derive(Debug)]
enum EnvironmentState {
    Inactive,
    Activating,
    Active {
        environment: Arc<ActiveEnvironment>,
        owned_runtime_refs: usize,
    },
}

#[derive(Debug)]
pub(crate) struct ActiveEnvironment {
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    embed_options: Option<EmbedContextOptions>,
    _temp_dir: TempDir,
}

impl std::fmt::Debug for SharedEnvironment {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SharedEnvironment")
            .field("cwd", &self.definition.cwd)
            .field("dependencies", &self.definition.dependencies.len())
            .field("active", &self.is_active())
            .finish()
    }
}

impl EnvironmentDefinition {
    pub(crate) fn from_mapping(
        cwd: PathBuf,
        dependencies: std::collections::BTreeMap<String, String>,
        lockfile_source: Option<PathBuf>,
    ) -> Result<Self, AnyError> {
        Ok(Self {
            cwd,
            dependencies: dependencies_from_mapping(dependencies)?,
            lockfile_source,
        })
    }

    pub(crate) fn from_folder(cwd: PathBuf, groups: Option<Vec<String>>) -> Result<Self, AnyError> {
        let dependencies = dependencies_from_folder(&cwd, groups)?;
        let lockfile = cwd.join("deno.lock");
        Ok(Self {
            cwd,
            dependencies,
            lockfile_source: lockfile.is_file().then_some(lockfile),
        })
    }

    pub(crate) fn cwd(&self) -> &Path {
        &self.cwd
    }

    pub(crate) fn dependency_count(&self) -> usize {
        self.dependencies.len()
    }
}

impl SharedEnvironment {
    pub(crate) fn new(definition: EnvironmentDefinition) -> Self {
        Self {
            definition: Arc::new(definition),
            state: Arc::new(Mutex::new(EnvironmentState::Inactive)),
        }
    }

    pub(crate) fn cwd(&self) -> &Path {
        self.definition.cwd()
    }

    pub(crate) fn dependency_count(&self) -> usize {
        self.definition.dependency_count()
    }

    pub(crate) fn is_active(&self) -> bool {
        matches!(
            *self
                .state
                .lock()
                .expect("environment state lock should not be poisoned"),
            EnvironmentState::Active { .. }
        )
    }

    pub(crate) fn activate_blocking(&self) -> Result<Arc<ActiveEnvironment>, AnyError> {
        pyo3_async_runtimes::tokio::get_runtime().block_on(self.activate_with_owned_refs(0))
    }

    pub(crate) fn activate_for_owned_runtime(&self) -> Result<Arc<ActiveEnvironment>, AnyError> {
        {
            let mut state = self
                .state
                .lock()
                .expect("environment state lock should not be poisoned");
            if let EnvironmentState::Active {
                environment,
                owned_runtime_refs,
            } = &mut *state
            {
                if *owned_runtime_refs == 0 {
                    return Err(anyhow!("Environment context is already active"));
                }
                *owned_runtime_refs += 1;
                return Ok(environment.clone());
            }
        }

        pyo3_async_runtimes::tokio::get_runtime().block_on(self.activate_with_owned_refs(1))
    }

    async fn activate_with_owned_refs(
        &self,
        owned_runtime_refs: usize,
    ) -> Result<Arc<ActiveEnvironment>, AnyError> {
        {
            let mut state = self
                .state
                .lock()
                .expect("environment state lock should not be poisoned");
            match &*state {
                EnvironmentState::Inactive => *state = EnvironmentState::Activating,
                EnvironmentState::Activating => {
                    return Err(anyhow!("Environment context is already being entered"));
                }
                EnvironmentState::Active { .. } => {
                    return Err(anyhow!("Environment context is already active"));
                }
            }
        }

        let active = ActiveEnvironment::create(&self.definition).await;
        let mut state = self
            .state
            .lock()
            .expect("environment state lock should not be poisoned");
        match active {
            Ok(active) => {
                let active = Arc::new(active);
                *state = EnvironmentState::Active {
                    environment: active.clone(),
                    owned_runtime_refs,
                };
                Ok(active)
            }
            Err(error) => {
                *state = EnvironmentState::Inactive;
                Err(error)
            }
        }
    }

    pub(crate) fn acquire_active(&self) -> Result<Arc<ActiveEnvironment>, AnyError> {
        let state = self
            .state
            .lock()
            .expect("environment state lock should not be poisoned");
        match &*state {
            EnvironmentState::Active { environment, .. } => Ok(environment.clone()),
            EnvironmentState::Activating => Err(anyhow!("Environment is still being activated")),
            EnvironmentState::Inactive => Err(anyhow!(
                "Environment must be entered before it can be used by Runtime"
            )),
        }
    }

    pub(crate) fn deactivate(&self) -> Result<(), AnyError> {
        let mut state = self
            .state
            .lock()
            .expect("environment state lock should not be poisoned");
        exit_error_if_not_active(&state)?;
        match &*state {
            EnvironmentState::Active {
                owned_runtime_refs: 0,
                ..
            } => {
                *state = EnvironmentState::Inactive;
                Ok(())
            }
            EnvironmentState::Active {
                owned_runtime_refs: 1..,
                ..
            } => Err(anyhow!(
                "Environment cannot exit while owned runtimes are still active"
            )),
            EnvironmentState::Activating | EnvironmentState::Inactive => unreachable!(),
        }
    }

    pub(crate) fn release_owned_runtime(&self) -> Result<(), AnyError> {
        let mut state = self
            .state
            .lock()
            .expect("environment state lock should not be poisoned");
        exit_error_if_not_active(&state)?;
        match &mut *state {
            EnvironmentState::Active {
                owned_runtime_refs: 0,
                ..
            } => Err(anyhow!("Environment has no owned runtime holders")),
            EnvironmentState::Active {
                owned_runtime_refs, ..
            } => {
                *owned_runtime_refs -= 1;
                if *owned_runtime_refs == 0 {
                    *state = EnvironmentState::Inactive;
                }
                Ok(())
            }
            EnvironmentState::Activating | EnvironmentState::Inactive => unreachable!(),
        }
    }
}

fn exit_error_if_not_active(state: &EnvironmentState) -> Result<(), AnyError> {
    match state {
        EnvironmentState::Activating => Err(anyhow!(
            "Environment cannot exit while it is being activated"
        )),
        EnvironmentState::Inactive => Err(anyhow!("Environment context is not active")),
        EnvironmentState::Active { .. } => Ok(()),
    }
}

impl ActiveEnvironment {
    async fn create(definition: &EnvironmentDefinition) -> Result<Self, AnyError> {
        let temp_dir = tempfile::Builder::new()
            .prefix("belgie-environment-")
            .tempdir()
            .context("Failed to create isolated Belgie environment")?;
        let config_file = temp_dir.path().join("deno.json");
        let lockfile = temp_dir.path().join("deno.lock");
        let cache_root = temp_dir.path().join("deno_dir");
        write_synthetic_config(&config_file, &definition.dependencies)?;
        std::fs::create_dir_all(&cache_root)
            .with_context(|| format!("Creating {}", cache_root.display()))?;

        let frozen_lockfile = if let Some(source) = &definition.lockfile_source {
            std::fs::copy(source, &lockfile).with_context(|| {
                format!(
                    "Copying lockfile from {} to {}",
                    source.display(),
                    lockfile.display()
                )
            })?;
            true
        } else {
            if definition.dependencies.is_empty() {
                std::fs::write(&lockfile, "{\"version\":\"5\"}\n")
                    .with_context(|| format!("Writing {}", lockfile.display()))?;
            }
            false
        };

        let embed_options = EmbedContextOptions {
            cache_root: Some(cache_root.clone()),
            frozen_lockfile: Some(frozen_lockfile),
            lockfile_skip_write: false,
        };
        if !definition.dependencies.is_empty() {
            let _embed_context = install_packages_with_options(
                definition.cwd.clone(),
                config_file.clone(),
                lockfile.clone(),
                false,
                embed_options.clone(),
            )
            .await?;
        }

        Ok(Self {
            cwd: definition.cwd.clone(),
            config_file,
            lockfile,
            embed_options: (!definition.dependencies.is_empty()).then_some(embed_options),
            _temp_dir: temp_dir,
        })
    }

    pub(crate) fn uses_package_loader(&self) -> bool {
        self.embed_options.is_some()
    }

    pub(crate) fn embed_context(&self) -> Result<EmbedContext, AnyError> {
        let options = self
            .embed_options
            .clone()
            .ok_or_else(|| anyhow!("Environment has no package dependencies"))?;
        EmbedContext::new_with_options(
            self.cwd.clone(),
            self.config_file.clone(),
            self.lockfile.clone(),
            options,
        )
    }

    #[cfg(test)]
    pub(crate) fn root(&self) -> &Path {
        self._temp_dir.path()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::fs;
    use std::sync::Arc;

    use super::{EnvironmentDefinition, SharedEnvironment};

    fn folder_environment() -> (tempfile::TempDir, SharedEnvironment) {
        let folder = tempfile::tempdir().unwrap();
        let environment = SharedEnvironment::new(
            EnvironmentDefinition::from_folder(folder.path().to_path_buf(), None).unwrap(),
        );
        (folder, environment)
    }

    #[test]
    fn empty_environment_uses_an_isolated_temporary_root() {
        let (_folder, environment) = folder_environment();

        let active = environment.activate_blocking().unwrap();
        let root = active.root().to_path_buf();

        assert!(root.is_dir());
        assert!(root.join("deno.json").is_file());
        assert!(root.join("deno.lock").is_file());
        assert!(root.join("deno_dir").is_dir());
        environment.deactivate().unwrap();
        drop(active);
        assert!(!root.exists());
    }

    #[test]
    fn direct_environment_normalizes_dependency_mappings() {
        let folder = tempfile::tempdir().unwrap();
        let definition = EnvironmentDefinition::from_mapping(
            folder.path().to_path_buf(),
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            None,
        )
        .unwrap();

        assert_eq!(definition.dependency_count(), 1);
    }

    #[test]
    fn folder_environment_does_not_modify_source_lockfile() {
        let folder = tempfile::tempdir().unwrap();
        fs::write(
            folder.path().join("pyproject.toml"),
            "[project]\nname = \"example\"\n",
        )
        .unwrap();
        fs::write(folder.path().join("deno.lock"), "{\"version\":\"5\"}\n").unwrap();
        let environment = SharedEnvironment::new(
            EnvironmentDefinition::from_folder(folder.path().to_path_buf(), None).unwrap(),
        );

        let active = environment.activate_blocking().unwrap();

        assert_eq!(
            fs::read_to_string(folder.path().join("deno.lock")).unwrap(),
            "{\"version\":\"5\"}\n"
        );
        assert_ne!(active.root(), folder.path());
    }

    #[test]
    fn nested_activation_is_rejected() {
        let (_folder, environment) = folder_environment();

        let _active = environment.activate_blocking().unwrap();
        let error = environment.activate_blocking().unwrap_err();

        assert!(error.to_string().contains("already active"));
    }

    #[test]
    fn owned_runtime_activation_can_be_shared() {
        let (_folder, environment) = folder_environment();

        let first = environment.activate_for_owned_runtime().unwrap();
        let second = environment.activate_for_owned_runtime().unwrap();

        assert!(Arc::ptr_eq(&first, &second));
        assert!(environment.is_active());

        environment.release_owned_runtime().unwrap();
        assert!(environment.is_active());

        environment.release_owned_runtime().unwrap();
        assert!(!environment.is_active());
    }

    #[test]
    fn activate_blocking_rejects_active_owned_runtime() {
        let (_folder, environment) = folder_environment();

        let _active = environment.activate_for_owned_runtime().unwrap();
        let error = environment.activate_blocking().unwrap_err();

        assert!(error.to_string().contains("already active"));
    }

    #[test]
    fn activate_for_owned_runtime_rejects_blocking_active() {
        let (_folder, environment) = folder_environment();

        let _active = environment.activate_blocking().unwrap();
        let error = environment.activate_for_owned_runtime().unwrap_err();

        assert!(error.to_string().contains("already active"));
    }

    #[test]
    fn deactivate_rejects_active_owned_runtime() {
        let (_folder, environment) = folder_environment();

        let _active = environment.activate_for_owned_runtime().unwrap();
        let error = environment.deactivate().unwrap_err();

        assert!(
            error
                .to_string()
                .contains("owned runtimes are still active")
        );
    }

    #[test]
    fn release_owned_runtime_rejects_blocking_active() {
        let (_folder, environment) = folder_environment();

        let _active = environment.activate_blocking().unwrap();
        let error = environment.release_owned_runtime().unwrap_err();

        assert!(error.to_string().contains("no owned runtime holders"));
    }
}
