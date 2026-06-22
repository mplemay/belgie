use std::borrow::Cow;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::Arc;

use deno_cache_dir::file_fetcher::MemoryFiles;
use deno_core::{FastString, ModuleSpecifier};
use deno_error::JsErrorBox;
use deno_lib::args::get_root_cert_store;
use deno_lib::npm::create_npm_process_state_provider;
use deno_lib::worker::{
    CreateModuleLoaderResult, LibMainWorker, LibMainWorkerFactory, LibMainWorkerOptions,
    LibWorkerFactoryRoots, ModuleLoaderFactory, StorageKeyResolver,
};
use deno_media_type::MediaType;
use deno_resolver::cjs::CjsTrackerRc;
use deno_resolver::npm::{DenoInNpmPackageChecker, NpmResolver};
use deno_runtime::deno_fs::RealFs;
use deno_runtime::deno_node::NodeRequireLoader;
use deno_runtime::deno_permissions::{Permissions, PermissionsContainer};
use deno_runtime::deno_tls::RootCertStoreProvider;
use deno_runtime::deno_tls::rustls::RootCertStore;
use deno_runtime::deno_web::{BlobStore, BlobStoreTrait};
use deno_runtime::permissions::RuntimePermissionDescriptorParser;
use deno_runtime::{FeatureChecker, WorkerExecutionMode, WorkerLogLevel};
use node_resolver::errors::PackageJsonLoadError;
use once_cell::sync::OnceCell;

use crate::embed::sys::EmbedSys;
use crate::embed::{EmbedContext, PackageRuntimeState, prepare_package_runtime};
use crate::runtime::error::map_package_environment_error;
use crate::runtime::module_loader::PackageAwareModuleLoader;
use crate::types::error::BindingError;

struct PackageWorkerSnapshotOptions {
    startup_snapshot: Option<&'static [u8]>,
    residual_lazy_js_sources: &'static [(&'static str, &'static str)],
    residual_lazy_esm_sources: &'static [(&'static str, &'static str)],
    skip_op_registration: bool,
}

fn package_worker_snapshot_options(use_cli_snapshot: bool) -> PackageWorkerSnapshotOptions {
    if use_cli_snapshot {
        PackageWorkerSnapshotOptions {
            startup_snapshot: deno_snapshots::CLI_SNAPSHOT,
            residual_lazy_js_sources: deno_snapshots::RESIDUAL_LAZY_JS,
            residual_lazy_esm_sources: deno_snapshots::RESIDUAL_LAZY_ESM,
            skip_op_registration: true,
        }
    } else {
        PackageWorkerSnapshotOptions {
            startup_snapshot: None,
            residual_lazy_js_sources: &[],
            residual_lazy_esm_sources: &[],
            skip_op_registration: false,
        }
    }
}

pub(crate) struct PackageWorkerOptions {
    pub argv: Vec<String>,
    pub argv0: Option<String>,
    pub use_cli_snapshot: bool,
}

pub(crate) struct BoundPackageWorkerOptions {
    pub argv: Vec<String>,
    pub argv0: Option<String>,
    pub use_cli_snapshot: bool,
    pub main_source: Option<String>,
    pub header_overrides: HashMap<ModuleSpecifier, HashMap<String, String>>,
}

pub(crate) async fn create_bound_package_worker(
    context: Rc<EmbedContext>,
    cwd: PathBuf,
    main_module: ModuleSpecifier,
    options: BoundPackageWorkerOptions,
) -> Result<LibMainWorker, BindingError> {
    let state = Arc::new(
        prepare_package_runtime(
            context.clone(),
            main_module.clone(),
            options.main_source,
            options.header_overrides,
        )
        .await
        .map_err(map_package_environment_error)?,
    );
    create_package_worker(
        state,
        context,
        cwd,
        main_module,
        PackageWorkerOptions {
            argv: options.argv,
            argv0: options.argv0,
            use_cli_snapshot: options.use_cli_snapshot,
        },
    )
}

fn default_lib_main_worker_options(
    cwd: &Path,
    snapshot: PackageWorkerSnapshotOptions,
    argv: Vec<String>,
    argv0: Option<String>,
) -> LibMainWorkerOptions {
    LibMainWorkerOptions {
        argv,
        log_level: WorkerLogLevel::Info,
        enable_raw_imports: false,
        enable_testing_features: false,
        has_node_modules_dir: true,
        inspect_brk: false,
        inspect_wait: false,
        trace_ops: None,
        is_inspecting: false,
        is_standalone: false,
        auto_serve: false,
        location: None,
        argv0,
        node_debug: std::env::var("NODE_DEBUG").ok(),
        node_cluster_unique_id: std::env::var("NODE_UNIQUE_ID").ok(),
        node_cluster_sched_policy: std::env::var("NODE_CLUSTER_SCHED_POLICY").ok(),
        otel_config: Default::default(),
        origin_data_folder_path: None,
        seed: None,
        unsafely_ignore_certificate_errors: None,
        skip_op_registration: snapshot.skip_op_registration,
        node_ipc_init: None,
        no_legacy_abort: true,
        startup_snapshot: snapshot.startup_snapshot,
        residual_lazy_js_sources: snapshot.residual_lazy_js_sources,
        residual_lazy_esm_sources: snapshot.residual_lazy_esm_sources,
        serve_port: None,
        serve_host: None,
        maybe_initial_cwd: ModuleSpecifier::from_directory_path(cwd).ok(),
    }
}

pub(crate) fn create_package_worker(
    state: Arc<PackageRuntimeState>,
    context: Rc<EmbedContext>,
    cwd: PathBuf,
    main_module: ModuleSpecifier,
    options: PackageWorkerOptions,
) -> Result<LibMainWorker, BindingError> {
    let resolver_factory = context.resolver_factory();
    let npm_resolver = resolver_factory
        .npm_resolver()
        .map_err(map_package_environment_error)?;
    let node_resolver = resolver_factory
        .node_resolver()
        .map_err(map_package_environment_error)?
        .clone();
    let module_loader_factory = Box::new(BelgieModuleLoaderFactory {
        state,
        initial_cwd: cwd.clone(),
        cjs_tracker: resolver_factory
            .cjs_tracker()
            .map_err(map_package_environment_error)?
            .clone(),
        npm_resolver: npm_resolver.clone(),
        memory_files: context.memory_files().clone(),
    });
    let permissions = PermissionsContainer::new(
        Arc::new(RuntimePermissionDescriptorParser::new(EmbedSys::default())),
        Permissions::allow_all(),
    );
    let snapshot_options = package_worker_snapshot_options(options.use_cli_snapshot);
    let main_module_url = url::Url::parse(main_module.as_str())
        .map_err(|error| BindingError::runtime(error.to_string()))?;
    LibMainWorkerFactory::new(
        BlobStore::default_arc() as Arc<dyn BlobStoreTrait>,
        None,
        None,
        Arc::new(FeatureChecker::default()),
        Arc::new(RealFs),
        None,
        None,
        module_loader_factory,
        node_resolver,
        create_npm_process_state_provider(npm_resolver),
        resolver_factory.pkg_json_resolver().clone(),
        Arc::new(BelgieRootCertStoreProvider::default()),
        StorageKeyResolver::empty(),
        EmbedSys::default(),
        default_lib_main_worker_options(&cwd, snapshot_options, options.argv, options.argv0),
        LibWorkerFactoryRoots::default(),
        None,
    )
    .create_main_worker(
        WorkerExecutionMode::Run,
        permissions,
        main_module_url,
        Vec::new(),
        Vec::new(),
    )
    .map_err(|error| BindingError::runtime(error.to_string()))
}

#[derive(Debug)]
struct BelgieModuleLoaderFactory {
    state: Arc<PackageRuntimeState>,
    initial_cwd: PathBuf,
    cjs_tracker: CjsTrackerRc<DenoInNpmPackageChecker, EmbedSys>,
    npm_resolver: NpmResolver<EmbedSys>,
    memory_files: deno_resolver::loader::MemoryFilesRc,
}

impl ModuleLoaderFactory for BelgieModuleLoaderFactory {
    fn create_for_main(&self, _root_permissions: PermissionsContainer) -> CreateModuleLoaderResult {
        self.create()
    }

    fn create_for_worker(
        &self,
        _parent_permissions: PermissionsContainer,
        _permissions: PermissionsContainer,
    ) -> CreateModuleLoaderResult {
        self.create()
    }
}

impl BelgieModuleLoaderFactory {
    fn create(&self) -> CreateModuleLoaderResult {
        CreateModuleLoaderResult {
            module_loader: Rc::new(PackageAwareModuleLoader::new(
                self.state.clone(),
                self.initial_cwd.clone(),
            )),
            node_require_loader: Rc::new(BelgieNodeRequireLoader {
                cjs_tracker: self.cjs_tracker.clone(),
                npm_resolver: self.npm_resolver.clone(),
                memory_files: self.memory_files.clone(),
            }),
            hook_registry: None,
        }
    }
}

#[derive(Debug)]
struct BelgieNodeRequireLoader {
    cjs_tracker: CjsTrackerRc<DenoInNpmPackageChecker, EmbedSys>,
    npm_resolver: NpmResolver<EmbedSys>,
    memory_files: deno_resolver::loader::MemoryFilesRc,
}

impl NodeRequireLoader for BelgieNodeRequireLoader {
    fn ensure_read_permission<'a>(
        &self,
        _permissions: &mut PermissionsContainer,
        path: Cow<'a, Path>,
    ) -> Result<Cow<'a, Path>, JsErrorBox> {
        Ok(path)
    }

    fn load_text_file_lossy(&self, path: &Path) -> Result<FastString, JsErrorBox> {
        let specifier = deno_path_util::url_from_file_path(path).map_err(JsErrorBox::from_err)?;
        if let Some(file) = self.memory_files.get(&specifier) {
            let source = file.source.as_ref();
            return Ok(match std::str::from_utf8(source) {
                Ok(text) => text.to_string().into(),
                Err(_) => String::from_utf8_lossy(source).into_owned().into(),
            });
        }
        let bytes = std::fs::read(path).map_err(JsErrorBox::from_err)?;
        Ok(match String::from_utf8(bytes) {
            Ok(text) => text.into(),
            Err(error) => String::from_utf8_lossy(error.as_bytes())
                .into_owned()
                .into(),
        })
    }

    fn is_maybe_cjs(&self, specifier: &ModuleSpecifier) -> Result<bool, PackageJsonLoadError> {
        self.cjs_tracker
            .is_maybe_cjs(specifier, MediaType::from_specifier(specifier))
    }

    fn is_maybe_cjs_from_require(
        &self,
        specifier: &ModuleSpecifier,
    ) -> Result<bool, PackageJsonLoadError> {
        self.cjs_tracker
            .is_maybe_cjs_from_require(specifier, MediaType::from_specifier(specifier))
    }

    fn resolve_require_node_module_paths(&self, from: &Path) -> Vec<String> {
        let uses_managed_global_cache = self
            .npm_resolver
            .as_managed()
            .filter(|resolver| resolver.root_node_modules_path().is_none())
            .map(|resolver| resolver.global_cache_root_path())
            .filter(|global_cache_path| from.starts_with(global_cache_path))
            .is_some();
        if uses_managed_global_cache {
            Vec::new()
        } else {
            deno_runtime::deno_node::default_resolve_require_node_module_paths(from)
        }
    }
}

#[derive(Debug, Default)]
struct BelgieRootCertStoreProvider {
    cell: OnceCell<RootCertStore>,
}

impl RootCertStoreProvider for BelgieRootCertStoreProvider {
    fn get_or_try_init(&self) -> Result<&RootCertStore, JsErrorBox> {
        self.cell
            .get_or_try_init(|| get_root_cert_store(&EmbedSys::default(), None, None, None))
            .map_err(JsErrorBox::from_err)
    }
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{default_lib_main_worker_options, package_worker_snapshot_options};

    #[test]
    fn package_worker_snapshot_options_enable_snapshot_and_skip_op_registration() {
        let snapshot = package_worker_snapshot_options(true);
        let options = default_lib_main_worker_options(Path::new("."), snapshot, vec![], None);
        assert!(options.startup_snapshot.is_some());
        assert!(!options.residual_lazy_js_sources.is_empty());
        assert!(!options.residual_lazy_esm_sources.is_empty());
        assert!(options.skip_op_registration);
    }

    #[test]
    fn package_worker_snapshot_options_disable_snapshot_and_op_skip_when_unavailable() {
        let snapshot = package_worker_snapshot_options(false);
        let options = default_lib_main_worker_options(Path::new("."), snapshot, vec![], None);
        assert!(options.startup_snapshot.is_none());
        assert!(options.residual_lazy_js_sources.is_empty());
        assert!(options.residual_lazy_esm_sources.is_empty());
        assert!(!options.skip_op_registration);
    }
}
