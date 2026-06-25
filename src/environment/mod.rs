use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use deno_core::anyhow::{Context, anyhow, bail};
use deno_core::error::AnyError;
use deno_resolver::cache::{DenoDirOptions, DenoDirProvider};
use tempfile::TempDir;

mod materialize;

use crate::embed::sys::EmbedSys;
use crate::embed::{EmbedContext, EmbedContextOptions};
use crate::options::{EnvironmentOptions, RuntimeWorkerOptions};
use crate::packages::{
    DependencyLayout, EMPTY_DENO_LOCK, EnvironmentInstallResult, EnvironmentUpdateRequest,
    EnvironmentUpdateResult, PackageDependency, dependencies_from_mapping,
    has_legacy_local_file_state, install_environment_packages, local_file_dependency_install_roots,
    specified_import_map, sync_local_file_dependencies, update_environment_packages,
};

#[derive(Clone, Debug)]
pub(crate) struct EnvironmentDefinition {
    workspace: PathBuf,
    persist_path: Option<PathBuf>,
    dependencies: Vec<PackageDependency>,
    layout: DependencyLayout,
    lockfile_source: Option<PathBuf>,
    cache: Option<PathBuf>,
    options: EnvironmentOptions,
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

enum EnvironmentRoot {
    Ephemeral {
        temp_dir: TempDir,
        materialized_node_modules: Mutex<Option<PathBuf>>,
    },
    Persisted,
}

pub(crate) struct ActiveEnvironment {
    workspace: PathBuf,
    lockfile: PathBuf,
    package_state: Mutex<ActivePackageState>,
    frozen_lockfile: bool,
    embed_options: EmbedContextOptions,
    root: EnvironmentRoot,
}

struct InstallLayout {
    lockfile: PathBuf,
    frozen_lockfile: bool,
    embed_options: EmbedContextOptions,
}

#[derive(Clone, Debug)]
struct ActivePackageState {
    dependencies: Vec<PackageDependency>,
    layout: DependencyLayout,
}

impl std::fmt::Debug for ActiveEnvironment {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ActiveEnvironment")
            .field("workspace", &self.workspace)
            .field("dependency_count", &self.dependency_count())
            .field("frozen_lockfile", &self.frozen_lockfile)
            .field("persisted", &self.is_persisted())
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
            .field("workspace", &self.definition.workspace)
            .field("persist_path", &self.definition.persist_path)
            .field("dependencies", &self.definition.dependencies.len())
            .field("active", &self.is_active())
            .finish()
    }
}

impl EnvironmentDefinition {
    #[cfg(test)]
    pub(crate) fn from_mapping(
        workspace: PathBuf,
        persist_path: Option<PathBuf>,
        dependencies: std::collections::BTreeMap<String, String>,
        lockfile_source: Option<PathBuf>,
        cache: Option<PathBuf>,
    ) -> Result<Self, AnyError> {
        Self::from_mapping_with_options(
            workspace,
            persist_path,
            dependencies,
            lockfile_source,
            cache,
            EnvironmentOptions::default(),
        )
    }

    pub(crate) fn from_mapping_with_options(
        workspace: PathBuf,
        persist_path: Option<PathBuf>,
        dependencies: std::collections::BTreeMap<String, String>,
        lockfile_source: Option<PathBuf>,
        cache: Option<PathBuf>,
        options: EnvironmentOptions,
    ) -> Result<Self, AnyError> {
        let dependencies = dependencies_from_mapping(&workspace, dependencies)?;
        let layout = DependencyLayout::from_dependencies(&dependencies);
        Ok(Self {
            workspace,
            persist_path,
            dependencies,
            layout,
            lockfile_source,
            cache,
            options,
        })
    }

    pub(crate) fn workspace(&self) -> &Path {
        &self.workspace
    }

    pub(crate) fn persist_path(&self) -> Option<&Path> {
        self.persist_path.as_deref()
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

    pub(crate) fn workspace(&self) -> &Path {
        self.definition.workspace()
    }

    pub(crate) fn persist_path(&self) -> Option<&Path> {
        self.definition.persist_path()
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
        crate::utils::tokio::block_on_outside_runtime(|| environment.activate())
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
        let environment = self.clone();
        crate::utils::tokio::block_on_outside_runtime(|| environment.lock(output_lockfile))
    }

    pub(crate) fn install_blocking(&self) -> Result<EnvironmentInstallResult, AnyError> {
        let environment = self.clone();
        crate::utils::tokio::block_on_outside_runtime(|| environment.install())
    }

    pub(crate) fn update_blocking(
        &self,
        packages: Vec<String>,
        latest: bool,
        lockfile_only: bool,
    ) -> Result<EnvironmentUpdateResult, AnyError> {
        let environment = self.clone();
        crate::utils::tokio::block_on_outside_runtime(|| {
            environment.update(packages, latest, lockfile_only)
        })
    }
}

fn copy_lockfile(from: &Path, to: &Path) -> Result<(), AnyError> {
    if from == to {
        return Ok(());
    }
    std::fs::copy(from, to).with_context(|| {
        format!(
            "Copying lockfile from {} to {}",
            from.display(),
            to.display()
        )
    })?;
    Ok(())
}

fn resolve_environment_cache(
    workspace: &Path,
    explicit: Option<&PathBuf>,
) -> Result<PathBuf, AnyError> {
    DenoDirProvider::new(
        EmbedSys::default(),
        DenoDirOptions {
            maybe_initial_cwd: Some(workspace.to_path_buf()),
            maybe_custom_root: explicit.cloned(),
        },
    )
    .get_or_create()
    .map(|dir| dir.root.clone())
    .map_err(AnyError::from)
}

fn install_root_url(install_root: &Path) -> Result<deno_core::url::Url, AnyError> {
    let absolute = std::path::absolute(install_root)
        .map(deno_path_util::strip_unc_prefix)
        .with_context(|| format!("Resolving {}", install_root.display()))?;
    deno_path_util::url_from_directory_path(&absolute).map_err(|error| {
        anyhow!(
            "Could not convert environment root {} to a file URL: {error}",
            absolute.display()
        )
    })
}

fn prepare_install_layout(
    install_root: &Path,
    definition: &EnvironmentDefinition,
) -> Result<InstallLayout, AnyError> {
    let lockfile = install_root.join("deno.lock");
    let node_modules_root = install_root.join("node_modules");

    let has_dependencies = !definition.dependencies.is_empty();

    let frozen_lockfile = if let Some(source) = &definition.lockfile_source {
        copy_lockfile(source, &lockfile)?;
        true
    } else {
        if !has_dependencies {
            std::fs::write(&lockfile, EMPTY_DENO_LOCK)
                .with_context(|| format!("Writing {}", lockfile.display()))?;
        }
        false
    };

    let node_modules_dir_mode = definition.options.node_modules_dir().or_else(|| {
        definition
            .layout
            .manual_node_modules
            .then_some(deno_config::deno_json::NodeModulesDirMode::Manual)
    });

    let mut embed_options = EmbedContextOptions {
        cache: definition.cache.clone(),
        cache_setting: definition.options.cache_setting().clone(),
        allow_remote: definition.options.allow_remote(),
        allow_json_imports: definition.options.allow_json_imports(),
        frozen_lockfile: None,
        is_package_manager_subcommand: false,
        lockfile_skip_write: false,
        node_modules_dir_mode,
        node_modules_linker: definition.options.node_modules_linker(),
        node_modules_root: Some(node_modules_root),
        no_npm: definition.options.no_npm(),
        npm_caching: definition.options.npm_caching(),
        clean_on_install: definition.options.clean_on_install(),
        production: definition.options.production(),
        skip_types: definition.options.skip_types(),
        unsafely_ignore_certificate_errors: definition.options.unsafely_ignore_certificate_errors(),
        specified_import_map: None,
        install_graph_roots: Vec::new(),
    };

    if has_dependencies || embed_options.requires_embed_module_loader() {
        embed_options.cache = Some(resolve_environment_cache(
            &definition.workspace,
            definition.cache.as_ref(),
        )?);
    }

    Ok(InstallLayout {
        lockfile,
        frozen_lockfile,
        embed_options,
    })
}

impl ActiveEnvironment {
    async fn create(definition: &EnvironmentDefinition) -> Result<Self, AnyError> {
        if let Some(path) = &definition.persist_path {
            Self::create_persisted(definition, path).await
        } else {
            Self::create_ephemeral(definition).await
        }
    }

    async fn create_persisted(
        definition: &EnvironmentDefinition,
        path: &Path,
    ) -> Result<Self, AnyError> {
        let layout = prepare_install_layout(path, definition)?;
        Ok(Self {
            workspace: definition.workspace.clone(),
            lockfile: layout.lockfile,
            package_state: Mutex::new(ActivePackageState {
                dependencies: definition.dependencies.clone(),
                layout: definition.layout,
            }),
            frozen_lockfile: layout.frozen_lockfile,
            embed_options: layout.embed_options,
            root: EnvironmentRoot::Persisted,
        })
    }

    async fn create_ephemeral(definition: &EnvironmentDefinition) -> Result<Self, AnyError> {
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
        let layout = prepare_install_layout(&temp_root, definition)?;
        Ok(Self {
            workspace: definition.workspace.clone(),
            lockfile: layout.lockfile,
            package_state: Mutex::new(ActivePackageState {
                dependencies: definition.dependencies.clone(),
                layout: definition.layout,
            }),
            frozen_lockfile: layout.frozen_lockfile,
            embed_options: layout.embed_options,
            root: EnvironmentRoot::Ephemeral {
                temp_dir,
                materialized_node_modules: Mutex::new(None),
            },
        })
    }

    fn is_persisted(&self) -> bool {
        matches!(self.root, EnvironmentRoot::Persisted)
    }

    fn dependency_count(&self) -> usize {
        self.package_state
            .lock()
            .expect("package state lock should not be poisoned")
            .dependencies
            .len()
    }

    fn with_package_state<R>(&self, f: impl FnOnce(&ActivePackageState) -> R) -> R {
        let package_state = self
            .package_state
            .lock()
            .expect("package state lock should not be poisoned");
        f(&package_state)
    }

    fn node_modules_root(&self) -> PathBuf {
        self.install_root().join("node_modules")
    }

    fn embed_options(&self) -> Result<EmbedContextOptions, AnyError> {
        let mut options = self.embed_options.clone();
        let base_url = install_root_url(self.install_root())?;
        let dependencies = self.with_package_state(|state| state.dependencies.clone());
        options.frozen_lockfile = Some(self.frozen_lockfile);
        options.specified_import_map = Some(specified_import_map(base_url, &dependencies)?);
        options.install_graph_roots = local_file_dependency_install_roots(&dependencies)?;
        Ok(options)
    }

    fn materialize_cwd_node_modules(&self) -> Result<(), AnyError> {
        if self.dependency_count() == 0 {
            return Ok(());
        }
        let EnvironmentRoot::Ephemeral {
            temp_dir,
            materialized_node_modules,
        } = &self.root
        else {
            return Ok(());
        };
        let temp_node_modules = temp_dir.path().join("node_modules");
        if let Some(materialized) =
            materialize::materialize_node_modules(&self.workspace, &temp_node_modules)?
        {
            *materialized_node_modules
                .lock()
                .expect("materialized node_modules lock should not be poisoned") =
                Some(materialized);
        }
        Ok(())
    }

    fn sync_local_file_dependencies(&self) -> Result<(), AnyError> {
        self.with_package_state(|package_state| {
            sync_local_file_dependencies(
                self.install_root(),
                &self.node_modules_root(),
                &package_state.dependencies,
            )
        })
    }

    pub(crate) fn refresh_local_file_dependencies(
        &self,
        already_synced: bool,
    ) -> Result<(), AnyError> {
        let has_legacy_state = has_legacy_local_file_state(self.install_root());
        let needs_refresh = self
            .with_package_state(|package_state| package_state.layout.has_local || has_legacy_state);
        if !needs_refresh {
            return Ok(());
        }
        if already_synced && !has_legacy_state {
            return Ok(());
        }
        self.sync_local_file_dependencies()
    }

    pub(crate) fn cleanup_materialized_node_modules(&self) -> Result<(), AnyError> {
        let EnvironmentRoot::Ephemeral {
            temp_dir,
            materialized_node_modules,
        } = &self.root
        else {
            return Ok(());
        };
        let mut materialized = materialized_node_modules
            .lock()
            .expect("materialized node_modules lock should not be poisoned");
        if let Some(path) = materialized.take() {
            let temp_node_modules = temp_dir.path().join("node_modules");
            materialize::cleanup_materialized(&path, &temp_node_modules)?;
        }
        Ok(())
    }

    pub(crate) fn embed_context(&self) -> Result<Rc<EmbedContext>, AnyError> {
        let options = self.embed_options()?;
        Ok(Rc::new(EmbedContext::new_with_options(
            self.workspace.clone(),
            self.lockfile.clone(),
            options,
        )?))
    }

    pub(crate) fn uses_package_loader(&self) -> bool {
        self.dependency_count() > 0
    }

    pub(crate) fn needs_package_environment(&self, worker_options: &RuntimeWorkerOptions) -> bool {
        self.uses_package_loader()
            || worker_options.requires_package_worker()
            || self.embed_options.requires_embed_module_loader()
    }

    pub(crate) fn has_package_dependencies(&self) -> bool {
        self.uses_package_loader()
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
        if self.dependency_count() == 0 {
            return Ok(EnvironmentInstallResult {
                lockfile: self.lockfile.clone(),
                dependencies: 0,
            });
        }
        let options = self.embed_options()?;
        let dependency_count = self.dependency_count();
        self.sync_local_file_dependencies()?;
        let lockfile = install_environment_packages(
            self.workspace.clone(),
            self.lockfile.clone(),
            lockfile_only,
            options,
        )
        .await?;
        self.refresh_local_file_dependencies(true)?;
        self.materialize_cwd_node_modules()?;
        Ok(EnvironmentInstallResult {
            lockfile,
            dependencies: dependency_count,
        })
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
        if self.dependency_count() == 0 {
            return Ok(EnvironmentUpdateResult {
                lockfile: self.lockfile.clone(),
                changes: Vec::new(),
                dependencies: Vec::new(),
            });
        }
        let options = self.embed_options()?;
        let dependencies = self.with_package_state(|state| state.dependencies.clone());
        self.sync_local_file_dependencies()?;
        let result = update_environment_packages(EnvironmentUpdateRequest {
            cwd: self.workspace.clone(),
            lockfile: self.lockfile.clone(),
            dependencies,
            packages,
            latest,
            lockfile_only,
            options,
        })
        .await?;
        {
            let mut package_state = self
                .package_state
                .lock()
                .expect("package state lock should not be poisoned");
            package_state.dependencies = result.dependencies.clone();
            package_state.layout = DependencyLayout::from_dependencies(&package_state.dependencies);
        }
        self.refresh_local_file_dependencies(true)?;
        self.materialize_cwd_node_modules()?;
        Ok(result)
    }

    pub(crate) fn install_root(&self) -> &Path {
        match &self.root {
            EnvironmentRoot::Ephemeral { temp_dir, .. } => temp_dir.path(),
            EnvironmentRoot::Persisted => &self.workspace,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::ffi::OsString;
    use std::path::PathBuf;
    use std::sync::Arc;

    use crate::environment::materialize::create_dangling_dir_symlink;

    use super::{ActiveEnvironment, EnvironmentDefinition, SharedEnvironment};

    // Tests mutate env vars; run serially.
    fn restore_env_var(name: &str, previous: Option<&OsString>) {
        match previous {
            Some(value) => {
                // SAFETY: single-threaded test env mutation.
                unsafe { std::env::set_var(name, value) };
            }
            None => {
                // SAFETY: single-threaded test env mutation.
                unsafe { std::env::remove_var(name) };
            }
        }
    }

    struct EnvVarGuard {
        name: &'static str,
        previous: Option<OsString>,
    }

    impl EnvVarGuard {
        fn set(name: &'static str, value: &str) -> Self {
            let previous = std::env::var_os(name);
            // SAFETY: single-threaded test env mutation.
            unsafe { std::env::set_var(name, value) };
            Self { name, previous }
        }

        fn remove(name: &'static str) -> Self {
            let previous = std::env::var_os(name);
            // SAFETY: single-threaded test env mutation.
            unsafe { std::env::remove_var(name) };
            Self { name, previous }
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            restore_env_var(self.name, self.previous.as_ref());
        }
    }

    struct ClearedCacheEnvGuards {
        _deno_dir: EnvVarGuard,
        _xdg_cache_home: EnvVarGuard,
        _home: EnvVarGuard,
    }

    fn cleared_cache_env() -> ClearedCacheEnvGuards {
        ClearedCacheEnvGuards {
            _deno_dir: EnvVarGuard::remove("DENO_DIR"),
            _xdg_cache_home: EnvVarGuard::remove("XDG_CACHE_HOME"),
            _home: EnvVarGuard::remove("HOME"),
        }
    }

    fn canonical_test_workspace(folder: &tempfile::TempDir) -> PathBuf {
        deno_path_util::strip_unc_prefix(
            folder
                .path()
                .canonicalize()
                .expect("workspace should canonicalize"),
        )
    }

    fn ephemeral_environment(workspace: std::path::PathBuf) -> SharedEnvironment {
        let definition =
            EnvironmentDefinition::from_mapping(workspace, None, BTreeMap::new(), None, None)
                .unwrap();
        SharedEnvironment::new(definition)
    }

    fn dependency_environment(workspace: PathBuf) -> SharedEnvironment {
        let definition = EnvironmentDefinition::from_mapping(
            workspace,
            None,
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            None,
            None,
        )
        .unwrap();
        SharedEnvironment::new(definition)
    }

    fn resolved_cache(active: &ActiveEnvironment) -> PathBuf {
        active
            .embed_options()
            .expect("embed options should resolve")
            .cache
            .expect("default cache should be resolved")
    }

    fn setup_materialized_npm_env() -> (
        tempfile::TempDir,
        PathBuf,
        SharedEnvironment,
        Arc<ActiveEnvironment>,
    ) {
        let folder = tempfile::tempdir().unwrap();
        let workspace = folder.path().to_path_buf();
        let definition = EnvironmentDefinition::from_mapping(
            workspace.clone(),
            None,
            BTreeMap::from([("pkg".to_string(), "npm:is-number@7.0.0".to_string())]),
            None,
            None,
        )
        .unwrap();
        let environment = SharedEnvironment::new(definition);
        let active = environment.activate_blocking().unwrap();
        let root = active.install_root().to_path_buf();
        std::fs::create_dir_all(root.join("node_modules")).unwrap();
        active.materialize_cwd_node_modules().unwrap();
        (folder, workspace, environment, active)
    }

    #[test]
    fn empty_environment_uses_an_isolated_temporary_root() {
        let folder = tempfile::tempdir().unwrap();
        let environment = ephemeral_environment(folder.path().to_path_buf());

        let active = environment.activate_blocking().unwrap();
        let root = active.install_root().to_path_buf();

        assert!(root.is_dir());
        assert!(!root.join("deno.json").exists());
        assert!(root.join("deno.lock").is_file());
        environment.deactivate().unwrap();
        drop(active);
        assert!(!root.exists());
    }

    #[test]
    fn empty_environment_skips_cache_resolution() {
        let folder = tempfile::tempdir().unwrap();
        let workspace = canonical_test_workspace(&folder);
        let environment = ephemeral_environment(workspace);
        let active = environment.activate_blocking().unwrap();

        assert!(active.embed_options().unwrap().cache.is_none());
        assert!(active.install_root().join("deno.lock").is_file());
        environment.deactivate().unwrap();
    }

    #[test]
    fn dependency_environment_requires_resolvable_cache() {
        let folder = tempfile::tempdir().unwrap();
        let workspace = canonical_test_workspace(&folder);
        let _env = cleared_cache_env();
        let result = dependency_environment(workspace).activate_blocking();
        if let Err(error) = result {
            let message = error.to_string().to_lowercase();
            assert!(
                message.contains("cache")
                    || message.contains("deno_dir")
                    || message.contains("home"),
                "unexpected error: {error}"
            );
        }
    }

    #[test]
    fn direct_environment_normalizes_dependency_mappings() {
        let folder = tempfile::tempdir().unwrap();
        let definition = EnvironmentDefinition::from_mapping(
            folder.path().to_path_buf(),
            None,
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            None,
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
            None,
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            None,
            None,
        )
        .unwrap();
        let environment = SharedEnvironment::new(definition);

        let active = environment.activate_blocking().unwrap();
        let root = active.install_root().to_path_buf();

        assert!(!root.join("deno.json").exists());
        assert!(!root.join("deno.lock").exists());
    }

    #[test]
    fn install_layout_does_not_create_per_environment_deno_dir() {
        let folder = tempfile::tempdir().unwrap();
        let definition = EnvironmentDefinition::from_mapping(
            folder.path().to_path_buf(),
            None,
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            None,
            None,
        )
        .unwrap();
        let environment = SharedEnvironment::new(definition);

        let active = environment.activate_blocking().unwrap();
        let root = active.install_root().to_path_buf();

        assert!(!root.join("deno_dir").exists());
        environment.deactivate().unwrap();
        drop(active);
    }

    #[test]
    fn relative_deno_dir_resolves_against_workspace_in_embed_options() {
        let folder = tempfile::tempdir().unwrap();
        let workspace = canonical_test_workspace(&folder);
        let _deno_dir = EnvVarGuard::set("DENO_DIR", "./.deno_cache");
        let environment = dependency_environment(workspace.clone());
        let active = environment.activate_blocking().unwrap();

        assert_eq!(resolved_cache(&active), workspace.join(".deno_cache"));
        environment.deactivate().unwrap();
    }

    #[test]
    fn nested_activation_is_rejected() {
        let folder = tempfile::tempdir().unwrap();
        let environment = ephemeral_environment(folder.path().to_path_buf());

        let _active = environment.activate_blocking().unwrap();
        let error = environment.activate_blocking().unwrap_err();

        assert!(error.to_string().contains("already active"));
    }

    #[test]
    fn active_reference_survives_environment_exit() {
        let folder = tempfile::tempdir().unwrap();
        let environment = ephemeral_environment(folder.path().to_path_buf());
        let active = environment.activate_blocking().unwrap();
        let root = active.install_root().to_path_buf();

        environment.deactivate().unwrap();

        assert!(!environment.is_active());
        assert!(root.exists());
        drop(active);
        assert!(!root.exists());
    }

    #[test]
    fn materialized_symlink_survives_environment_exit_while_reference_held() {
        let (_folder, workspace, environment, active) = setup_materialized_npm_env();
        let root = active.install_root().to_path_buf();
        let symlink = workspace.join("node_modules");
        assert!(symlink.is_symlink());

        environment.deactivate().unwrap();

        assert!(!environment.is_active());
        assert!(symlink.exists());
        assert!(root.exists());
        drop(active);
        assert!(!symlink.exists());
        assert!(!root.exists());
    }

    #[test]
    fn materialized_symlink_is_removed_when_last_reference_drops() {
        let (_folder, workspace, environment, active) = setup_materialized_npm_env();
        let root = active.install_root().to_path_buf();
        let symlink = workspace.join("node_modules");
        assert!(symlink.is_symlink());

        let runtime_ref = Arc::clone(&active);
        drop(active);
        drop(runtime_ref);
        environment.deactivate().unwrap();

        assert!(!symlink.exists());
        assert!(!root.exists());
    }

    #[test]
    fn preexisting_dangling_symlink_survives_noop_materialization() {
        let folder = tempfile::tempdir().unwrap();
        let workspace = folder.path().join("process");
        std::fs::create_dir_all(&workspace).unwrap();
        let dangling_target = folder.path().join("missing").join("node_modules");
        create_dangling_dir_symlink(&workspace.join("node_modules"), &dangling_target);

        let symlink = workspace.join("node_modules");
        assert!(symlink.is_symlink());
        assert!(!symlink.exists());

        let definition = EnvironmentDefinition::from_mapping(
            workspace.clone(),
            None,
            BTreeMap::from([("pkg".to_string(), "npm:is-number@7.0.0".to_string())]),
            None,
            None,
        )
        .unwrap();
        let environment = SharedEnvironment::new(definition);
        let active = environment.activate_blocking().unwrap();
        active.materialize_cwd_node_modules().unwrap();

        environment.deactivate().unwrap();
        drop(active);

        assert!(symlink.is_symlink());
        assert!(!symlink.exists());
    }

    #[test]
    fn persisted_environment_preserves_lockfile_when_source_matches_install_target() {
        let folder = tempfile::tempdir().unwrap();
        let project = folder.path().join("project");
        std::fs::create_dir_all(&project).unwrap();
        let lockfile = project.join("deno.lock");
        let lock_content = r#"{"version":"5","specifiers":{"jsr:@std/path":"^1.0.0"}}"#;
        std::fs::write(&lockfile, lock_content).unwrap();

        let definition = EnvironmentDefinition::from_mapping(
            project.clone(),
            Some(project.clone()),
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            Some(lockfile.clone()),
            None,
        )
        .unwrap();
        let environment = SharedEnvironment::new(definition);

        let active = environment.activate_blocking().unwrap();
        environment.deactivate().unwrap();
        drop(active);

        assert_eq!(std::fs::read_to_string(&lockfile).unwrap(), lock_content);
    }

    #[test]
    fn persisted_environment_keeps_install_artifacts_after_exit() {
        let folder = tempfile::tempdir().unwrap();
        let project = folder.path().join("project");
        std::fs::create_dir_all(&project).unwrap();
        let definition = EnvironmentDefinition::from_mapping(
            project.clone(),
            Some(project.clone()),
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
            None,
            None,
        )
        .unwrap();
        let environment = SharedEnvironment::new(definition);

        let active = environment.activate_blocking().unwrap();
        environment.deactivate().unwrap();
        drop(active);

        assert!(!project.join("deno.json").exists());
    }
}
