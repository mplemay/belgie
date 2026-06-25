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
use deno_runtime::deno_permissions::PermissionsContainer;
use deno_runtime::deno_tls::RootCertStoreProvider;
use deno_runtime::deno_tls::rustls::RootCertStore;
use deno_runtime::deno_web::{BlobStore, BlobStoreTrait};
use deno_runtime::permissions::RuntimePermissionDescriptorParser;
use deno_runtime::{
    FeatureChecker, UnconfiguredRuntimeOptions, WorkerExecutionMode, WorkerLogLevel,
};
use node_resolver::errors::PackageJsonLoadError;
use once_cell::sync::OnceCell;

use crate::embed::sys::EmbedSys;
use crate::embed::{EmbedContext, PackageRuntimeState, prepare_package_runtime};
use crate::options::{JsRuntimeOptions, RuntimeWorkerOptions};
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
    pub js_runtime_options: JsRuntimeOptions,
    pub runtime_worker_options: RuntimeWorkerOptions,
}

pub(crate) struct BoundPackageWorkerOptions {
    pub argv: Vec<String>,
    pub argv0: Option<String>,
    pub use_cli_snapshot: bool,
    pub js_runtime_options: JsRuntimeOptions,
    pub runtime_worker_options: RuntimeWorkerOptions,
    pub main_source: Option<String>,
    pub header_overrides: HashMap<ModuleSpecifier, HashMap<String, String>>,
}

pub(crate) async fn create_bound_package_worker(
    context: Rc<EmbedContext>,
    cwd: PathBuf,
    main_module: ModuleSpecifier,
    options: BoundPackageWorkerOptions,
    roots: &LibWorkerFactoryRoots,
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
            js_runtime_options: options.js_runtime_options,
            runtime_worker_options: options.runtime_worker_options,
        },
        roots,
    )
}

fn default_lib_main_worker_options(
    cwd: &Path,
    snapshot: PackageWorkerSnapshotOptions,
    argv: Vec<String>,
    argv0: Option<String>,
    runtime_worker_options: &RuntimeWorkerOptions,
    unsafely_ignore_certificate_errors: Option<Vec<String>>,
) -> LibMainWorkerOptions {
    LibMainWorkerOptions {
        argv,
        log_level: runtime_worker_options
            .log_level()
            .unwrap_or(WorkerLogLevel::Info),
        enable_raw_imports: runtime_worker_options.enable_raw_imports(),
        enable_testing_features: runtime_worker_options.enable_testing_features(),
        has_node_modules_dir: true,
        inspect_brk: false,
        inspect_wait: false,
        trace_ops: runtime_worker_options.trace_ops(),
        is_inspecting: false,
        is_standalone: false,
        auto_serve: false,
        location: runtime_worker_options.location(),
        argv0,
        node_debug: std::env::var("NODE_DEBUG").ok(),
        node_cluster_unique_id: std::env::var("NODE_UNIQUE_ID").ok(),
        node_cluster_sched_policy: std::env::var("NODE_CLUSTER_SCHED_POLICY").ok(),
        otel_config: Default::default(),
        origin_data_folder_path: None,
        seed: runtime_worker_options.seed(),
        unsafely_ignore_certificate_errors,
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
    roots: &LibWorkerFactoryRoots,
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
        options
            .runtime_worker_options
            .permissions()
            .to_permissions()
            .map_err(BindingError::runtime)?,
    );
    let snapshot_options = package_worker_snapshot_options(options.use_cli_snapshot);
    let unconfigured_runtime =
        create_unconfigured_runtime(&snapshot_options, &options.js_runtime_options, roots)?;
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
        default_lib_main_worker_options(
            &cwd,
            snapshot_options,
            options.argv,
            options.argv0,
            &options.runtime_worker_options,
            context.unsafely_ignore_certificate_errors(),
        ),
        roots.clone(),
        None,
    )
    .create_custom_worker(
        WorkerExecutionMode::Run,
        main_module_url,
        Vec::new(),
        Vec::new(),
        permissions,
        Vec::new(),
        Default::default(),
        unconfigured_runtime,
    )
    .map_err(|error| BindingError::runtime(error.to_string()))
}

fn create_unconfigured_runtime(
    snapshot: &PackageWorkerSnapshotOptions,
    js_runtime_options: &JsRuntimeOptions,
    roots: &LibWorkerFactoryRoots,
) -> Result<Option<deno_runtime::UnconfiguredRuntime>, BindingError> {
    let Some(create_params) = js_runtime_options
        .to_create_params()
        .map_err(BindingError::runtime)?
    else {
        return Ok(None);
    };
    let Some(startup_snapshot) = snapshot.startup_snapshot else {
        return Err(BindingError::runtime(
            "Package worker V8 memory options require the Deno CLI snapshot to be available",
        ));
    };
    Ok(Some(deno_runtime::UnconfiguredRuntime::new::<
        DenoInNpmPackageChecker,
        NpmResolver<EmbedSys>,
        EmbedSys,
    >(UnconfiguredRuntimeOptions {
        startup_snapshot,
        residual_lazy_js_sources: snapshot.residual_lazy_js_sources,
        residual_lazy_esm_sources: snapshot.residual_lazy_esm_sources,
        create_params: Some(create_params),
        shared_array_buffer_store: Some(roots.shared_array_buffer_store.clone()),
        compiled_wasm_module_store: Some(roots.compiled_wasm_module_store.clone()),
        additional_extensions: Vec::new(),
    })))
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
        self.create(false)
    }

    fn create_for_worker(
        &self,
        _parent_permissions: PermissionsContainer,
        _permissions: PermissionsContainer,
    ) -> CreateModuleLoaderResult {
        self.create(true)
    }
}

impl BelgieModuleLoaderFactory {
    fn create(&self, is_worker: bool) -> CreateModuleLoaderResult {
        let state = if is_worker {
            Arc::new(self.state.with_empty_graph())
        } else {
            self.state.clone()
        };
        CreateModuleLoaderResult {
            module_loader: Rc::new(PackageAwareModuleLoader::new(
                state,
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

    use deno_runtime::WorkerLogLevel;

    use crate::options::{JsRuntimeOptions, RuntimePermissionOptions, RuntimeWorkerOptions};

    use super::{
        create_unconfigured_runtime, default_lib_main_worker_options,
        package_worker_snapshot_options,
    };

    #[test]
    fn package_worker_snapshot_options_enable_snapshot_and_skip_op_registration() {
        let snapshot = package_worker_snapshot_options(true);
        let worker_options = RuntimeWorkerOptions::default();
        let options = default_lib_main_worker_options(
            Path::new("."),
            snapshot,
            vec![],
            None,
            &worker_options,
            None,
        );
        assert!(options.startup_snapshot.is_some());
        assert!(!options.residual_lazy_js_sources.is_empty());
        assert!(!options.residual_lazy_esm_sources.is_empty());
        assert!(options.skip_op_registration);
    }

    #[test]
    fn package_worker_snapshot_options_disable_snapshot_and_op_skip_when_unavailable() {
        let snapshot = package_worker_snapshot_options(false);
        let worker_options = RuntimeWorkerOptions::default();
        let options = default_lib_main_worker_options(
            Path::new("."),
            snapshot,
            vec![],
            None,
            &worker_options,
            None,
        );
        assert!(options.startup_snapshot.is_none());
        assert!(options.residual_lazy_js_sources.is_empty());
        assert!(options.residual_lazy_esm_sources.is_empty());
        assert!(!options.skip_op_registration);
    }

    #[test]
    fn lib_main_worker_options_apply_runtime_worker_options() {
        let snapshot = package_worker_snapshot_options(false);
        let location = url::Url::parse("https://example.com/app").unwrap();
        let worker_options = RuntimeWorkerOptions::new(
            RuntimePermissionOptions::AllowAll,
            Some(123),
            Some(location.clone()),
            Some(WorkerLogLevel::Debug),
            true,
            true,
            Some(vec!["fs".to_string()]),
        );

        let options = default_lib_main_worker_options(
            Path::new("."),
            snapshot,
            vec![],
            None,
            &worker_options,
            Some(vec!["localhost".to_string()]),
        );

        assert_eq!(options.seed, Some(123));
        assert_eq!(options.location, Some(location));
        assert!(matches!(options.log_level, WorkerLogLevel::Debug));
        assert!(options.enable_testing_features);
        assert!(options.enable_raw_imports);
        assert_eq!(options.trace_ops, Some(vec!["fs".to_string()]));
        assert_eq!(
            options.unsafely_ignore_certificate_errors,
            Some(vec!["localhost".to_string()])
        );
    }

    #[test]
    fn custom_v8_params_report_missing_snapshot() {
        let snapshot = package_worker_snapshot_options(false);
        let roots = deno_lib::worker::LibWorkerFactoryRoots::default();
        let result = create_unconfigured_runtime(
            &snapshot,
            &JsRuntimeOptions::new(Some(64), None, None),
            &roots,
        );

        let Err(error) = result else {
            panic!("expected missing snapshot error");
        };
        assert!(error.message().contains("CLI snapshot"));
    }
}
