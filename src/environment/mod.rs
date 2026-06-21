use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use deno_core::anyhow::{Context, anyhow, bail};
use deno_core::error::AnyError;
use tempfile::TempDir;

mod materialize;

use crate::embed::{EmbedContext, EmbedContextOptions};
use crate::packages::{
    EMPTY_DENO_LOCK, EnvironmentInstallResult, EnvironmentUpdateRequest, EnvironmentUpdateResult,
    PackageDependency, dependencies_from_mapping, install_environment_packages,
    update_environment_packages, write_synthetic_config,
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
    Active(Arc<ActiveEnvironment>),
}

pub(crate) struct ActiveEnvironment {
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    dependency_count: usize,
    frozen_lockfile: bool,
    embed_options: Option<EmbedContextOptions>,
    materialized_node_modules: Mutex<Option<PathBuf>>,
    temp_dir: TempDir,
}

impl std::fmt::Debug for ActiveEnvironment {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ActiveEnvironment")
            .field("cwd", &self.cwd)
            .field("dependency_count", &self.dependency_count)
            .field("frozen_lockfile", &self.frozen_lockfile)
            .field("materialized_node_modules", &self.materialized_node_modules)
            .finish_non_exhaustive()
    }
}

impl Drop for ActiveEnvironment {
    fn drop(&mut self) {
        let _ = self.cleanup_materialized_node_modules();
    }
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
        let environment = self.clone();
        crate::utils::tokio::run_outside_runtime(move || {
            pyo3_async_runtimes::tokio::get_runtime().block_on(environment.activate())
        })
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
            EnvironmentState::Active(environment) => {
                environment.cleanup_materialized_node_modules()?;
            }
        }
        *state = EnvironmentState::Inactive;
        Ok(())
    }

    pub(crate) async fn lock(
        &self,
        output_lockfile: Option<PathBuf>,
    ) -> Result<EnvironmentInstallResult, AnyError> {
        self.acquire_active()?.lock(output_lockfile).await
    }

    pub(crate) async fn install(&self) -> Result<EnvironmentInstallResult, AnyError> {
        self.acquire_active()?.install().await
    }

    pub(crate) async fn update(
        &self,
        packages: Vec<String>,
        latest: bool,
        lockfile_only: bool,
    ) -> Result<EnvironmentUpdateResult, AnyError> {
        self.acquire_active()?
            .update(packages, latest, lockfile_only)
            .await
    }

    pub(crate) fn lock_blocking(
        &self,
        output_lockfile: Option<PathBuf>,
    ) -> Result<EnvironmentInstallResult, AnyError> {
        let _active = self.acquire_active()?;
        let environment = self.clone();
        crate::utils::tokio::run_outside_runtime(move || {
            pyo3_async_runtimes::tokio::get_runtime().block_on(environment.lock(output_lockfile))
        })
    }

    pub(crate) fn install_blocking(&self) -> Result<EnvironmentInstallResult, AnyError> {
        let _active = self.acquire_active()?;
        let environment = self.clone();
        crate::utils::tokio::run_outside_runtime(move || {
            pyo3_async_runtimes::tokio::get_runtime().block_on(environment.install())
        })
    }

    pub(crate) fn update_blocking(
        &self,
        packages: Vec<String>,
        latest: bool,
        lockfile_only: bool,
    ) -> Result<EnvironmentUpdateResult, AnyError> {
        let _active = self.acquire_active()?;
        let environment = self.clone();
        crate::utils::tokio::run_outside_runtime(move || {
            pyo3_async_runtimes::tokio::get_runtime().block_on(environment.update(
                packages,
                latest,
                lockfile_only,
            ))
        })
    }
}

fn copy_lockfile(from: &Path, to: &Path) -> Result<(), AnyError> {
    std::fs::copy(from, to).with_context(|| {
        format!(
            "Copying lockfile from {} to {}",
            from.display(),
            to.display()
        )
    })?;
    Ok(())
}

impl ActiveEnvironment {
    async fn create(definition: &EnvironmentDefinition) -> Result<Self, AnyError> {
        let temp_dir = tempfile::Builder::new()
            .prefix("belgie-environment-")
            .tempdir()
            .context("Failed to create isolated Belgie environment")?;
        let temp_root = deno_path_util::strip_unc_prefix(
            temp_dir
                .path()
                .canonicalize()
                .context("Failed to canonicalize isolated Belgie environment")?,
        );
        let config_file = temp_root.join("deno.json");
        let lockfile = temp_root.join("deno.lock");
        let cache_root = temp_root.join("deno_dir");
        let node_modules_root = temp_root.join("node_modules");
        write_synthetic_config(&config_file, &definition.dependencies)?;
        std::fs::create_dir_all(&cache_root)
            .with_context(|| format!("Creating {}", cache_root.display()))?;

        let frozen_lockfile = if let Some(source) = &definition.lockfile_source {
            copy_lockfile(source, &lockfile)?;
            true
        } else {
            if definition.dependencies.is_empty() {
                std::fs::write(&lockfile, EMPTY_DENO_LOCK)
                    .with_context(|| format!("Writing {}", lockfile.display()))?;
            }
            false
        };

        let embed_options = EmbedContextOptions {
            cache_root: Some(cache_root.clone()),
            frozen_lockfile: Some(frozen_lockfile),
            lockfile_skip_write: false,
            node_modules_root: Some(node_modules_root),
        };
        Ok(Self {
            cwd: definition.cwd.clone(),
            config_file,
            lockfile,
            dependency_count: definition.dependencies.len(),
            frozen_lockfile,
            embed_options: (!definition.dependencies.is_empty()).then_some(embed_options),
            materialized_node_modules: Mutex::new(None),
            temp_dir,
        })
    }

    fn materialize_cwd_node_modules(&self) -> Result<(), AnyError> {
        if self.dependency_count == 0 {
            return Ok(());
        }
        let temp_node_modules = self.temp_dir.path().join("node_modules");
        let materialized = materialize::materialize_node_modules(&self.cwd, &temp_node_modules)?;
        *self
            .materialized_node_modules
            .lock()
            .expect("materialized node_modules lock should not be poisoned") = Some(materialized);
        Ok(())
    }

    pub(crate) fn cleanup_materialized_node_modules(&self) -> Result<(), AnyError> {
        let mut materialized = self
            .materialized_node_modules
            .lock()
            .expect("materialized node_modules lock should not be poisoned");
        if let Some(path) = materialized.take() {
            let temp_node_modules = self.temp_dir.path().join("node_modules");
            materialize::cleanup_materialized(&path, &temp_node_modules)?;
        }
        Ok(())
    }

    pub(crate) fn embed_context(&self) -> Result<Rc<EmbedContext>, AnyError> {
        debug_assert!(self.temp_dir.path().is_dir());
        let options = self
            .embed_options
            .clone()
            .ok_or_else(|| anyhow!("Environment has no package dependencies"))?;
        Ok(Rc::new(EmbedContext::new_with_options(
            self.cwd.clone(),
            self.config_file.clone(),
            self.lockfile.clone(),
            options,
        )?))
    }

    pub(crate) fn uses_package_loader(&self) -> bool {
        self.embed_options.is_some()
    }

    async fn lock(
        &self,
        output_lockfile: Option<PathBuf>,
    ) -> Result<EnvironmentInstallResult, AnyError> {
        let mut result = self.install_with_lockfile_only(true).await?;
        if let Some(output_lockfile) = output_lockfile {
            copy_lockfile(&result.lockfile, &output_lockfile)?;
            result.lockfile = output_lockfile;
        }
        Ok(result)
    }

    async fn install(&self) -> Result<EnvironmentInstallResult, AnyError> {
        self.install_with_lockfile_only(false).await
    }

    async fn install_with_lockfile_only(
        &self,
        lockfile_only: bool,
    ) -> Result<EnvironmentInstallResult, AnyError> {
        let Some(options) = self.embed_options.clone() else {
            return Ok(EnvironmentInstallResult {
                lockfile: self.lockfile.clone(),
                dependencies: 0,
            });
        };
        let result = install_environment_packages(
            self.cwd.clone(),
            self.config_file.clone(),
            self.lockfile.clone(),
            self.dependency_count,
            lockfile_only,
            options,
        )
        .await?;
        self.materialize_cwd_node_modules()?;
        Ok(result)
    }

    async fn update(
        &self,
        packages: Vec<String>,
        latest: bool,
        lockfile_only: bool,
    ) -> Result<EnvironmentUpdateResult, AnyError> {
        if self.frozen_lockfile {
            bail!("Cannot update an Environment created with a frozen lockfile");
        }
        let Some(options) = self.embed_options.clone() else {
            return Ok(EnvironmentUpdateResult {
                lockfile: self.lockfile.clone(),
                changes: Vec::new(),
            });
        };
        let result = update_environment_packages(EnvironmentUpdateRequest {
            cwd: self.cwd.clone(),
            config_file: self.config_file.clone(),
            lockfile: self.lockfile.clone(),
            dependencies: self.dependency_count,
            packages,
            latest,
            lockfile_only,
            options,
        })
        .await?;
        self.materialize_cwd_node_modules()?;
        Ok(result)
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
    fn entering_dependency_environment_does_not_install_packages() {
        let folder = tempfile::tempdir().unwrap();
        let definition = EnvironmentDefinition::from_mapping(
            folder.path().to_path_buf(),
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            None,
        )
        .unwrap();
        let environment = SharedEnvironment::new(definition);

        let active = environment.activate_blocking().unwrap();
        let root = active.root().to_path_buf();

        assert!(root.join("deno.json").is_file());
        assert!(!root.join("deno.lock").exists());
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
