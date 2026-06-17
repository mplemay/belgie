use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use deno_core::anyhow::{Context, anyhow};
use deno_core::error::AnyError;
use tempfile::TempDir;

use crate::embed::{EmbedContext, EmbedContextOptions, install_packages_with_options};
use crate::packages::{PackageDependency, dependencies_from_mapping, write_synthetic_config};

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
    Active(Arc<ActiveEnvironment>),
}

#[derive(Debug)]
pub(crate) struct ActiveEnvironment {
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    embed_options: Option<EmbedContextOptions>,
    temp_dir: TempDir,
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
            EnvironmentState::Active(_)
        )
    }

    pub(crate) fn activate_blocking(&self) -> Result<Arc<ActiveEnvironment>, AnyError> {
        pyo3_async_runtimes::tokio::get_runtime().block_on(self.activate())
    }

    async fn activate(&self) -> Result<Arc<ActiveEnvironment>, AnyError> {
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
                EnvironmentState::Active(_) => {
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
                *state = EnvironmentState::Active(active.clone());
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
            EnvironmentState::Active(environment) => Ok(environment.clone()),
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
        match &*state {
            EnvironmentState::Activating => {
                return Err(anyhow!(
                    "Environment cannot exit while it is being activated"
                ));
            }
            EnvironmentState::Inactive => {
                return Err(anyhow!("Environment context is not active"));
            }
            EnvironmentState::Active(_) => {}
        }
        *state = EnvironmentState::Inactive;
        Ok(())
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
            node_modules_root: None,
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
            temp_dir,
        })
    }

    pub(crate) fn embed_context(&self) -> Result<EmbedContext, AnyError> {
        debug_assert!(self.temp_dir.path().is_dir());
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

    pub(crate) fn uses_package_loader(&self) -> bool {
        self.embed_options.is_some()
    }

    #[cfg(test)]
    pub(crate) fn root(&self) -> &Path {
        self.temp_dir.path()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::{EnvironmentDefinition, SharedEnvironment};

    fn empty_environment() -> (tempfile::TempDir, SharedEnvironment) {
        let folder = tempfile::tempdir().unwrap();
        let definition =
            EnvironmentDefinition::from_mapping(folder.path().to_path_buf(), BTreeMap::new(), None)
                .unwrap();
        (folder, SharedEnvironment::new(definition))
    }

    #[test]
    fn empty_environment_uses_an_isolated_temporary_root() {
        let (_folder, environment) = empty_environment();

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
    fn nested_activation_is_rejected() {
        let (_folder, environment) = empty_environment();

        let _active = environment.activate_blocking().unwrap();
        let error = environment.activate_blocking().unwrap_err();

        assert!(error.to_string().contains("already active"));
    }

    #[test]
    fn active_reference_survives_environment_exit() {
        let (_folder, environment) = empty_environment();
        let active = environment.activate_blocking().unwrap();
        let root = active.root().to_path_buf();

        environment.deactivate().unwrap();

        assert!(!environment.is_active());
        assert!(root.exists());
        drop(active);
        assert!(!root.exists());
    }
}
