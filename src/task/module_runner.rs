use std::borrow::Cow;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::Arc;

use deno_core::FastString;
use deno_core::error::AnyError;
use deno_error::JsErrorBox;
use deno_lib::args::get_root_cert_store;
use deno_lib::npm::create_npm_process_state_provider;
use deno_lib::worker::{
    CreateModuleLoaderResult, LibMainWorkerFactory, LibMainWorkerOptions, LibWorkerFactoryRoots,
    ModuleLoaderFactory, StorageKeyResolver,
};
use deno_media_type::MediaType;
use deno_permissions::PermissionsContainer;
use deno_resolver::cjs::CjsTrackerRc;
use deno_resolver::npm::DenoInNpmPackageChecker;
use deno_runtime::deno_fs::RealFs;
use deno_runtime::deno_node::NodeRequireLoader;
use deno_runtime::deno_permissions::RuntimePermissionDescriptorParser;
use deno_runtime::deno_tls::RootCertStoreProvider;
use deno_runtime::deno_tls::rustls::RootCertStore;
use deno_runtime::{FeatureChecker, WorkerExecutionMode, WorkerLogLevel};
use node_resolver::errors::PackageJsonLoadError;
use url::Url;

use crate::embed::EmbedContext;
use crate::embed::sys::EmbedSys;
use crate::embed::{PackageRuntimeState, prepare_package_runtime};
use crate::packages::{project_embed_options, project_state_error};
use crate::runtime::module_loader::PackageAwareModuleLoader;

#[derive(Clone)]
struct TaskModuleLoaderFactory {
    state: Arc<PackageRuntimeState>,
    cjs_tracker: CjsTrackerRc<DenoInNpmPackageChecker, EmbedSys>,
    initial_cwd: PathBuf,
}

impl TaskModuleLoaderFactory {
    fn create(&self) -> CreateModuleLoaderResult {
        CreateModuleLoaderResult {
            module_loader: Rc::new(PackageAwareModuleLoader::new(
                Arc::clone(&self.state),
                self.initial_cwd.clone(),
            )),
            node_require_loader: Rc::new(TaskNodeRequireLoader {
                cjs_tracker: self.cjs_tracker.clone(),
            }),
            hook_registry: None,
        }
    }
}

impl ModuleLoaderFactory for TaskModuleLoaderFactory {
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

struct TaskNodeRequireLoader {
    cjs_tracker: CjsTrackerRc<DenoInNpmPackageChecker, EmbedSys>,
}

impl NodeRequireLoader for TaskNodeRequireLoader {
    fn ensure_read_permission<'a>(
        &self,
        _permissions: &mut PermissionsContainer,
        path: Cow<'a, Path>,
    ) -> Result<Cow<'a, Path>, JsErrorBox> {
        Ok(path)
    }

    fn load_text_file_lossy(&self, path: &Path) -> Result<FastString, JsErrorBox> {
        std::fs::read_to_string(path)
            .map(Into::into)
            .map_err(JsErrorBox::from_err)
    }

    fn is_maybe_cjs(&self, specifier: &Url) -> Result<bool, PackageJsonLoadError> {
        self.cjs_tracker
            .is_maybe_cjs(specifier, MediaType::from_specifier(specifier))
    }

    fn is_maybe_cjs_from_require(&self, specifier: &Url) -> Result<bool, PackageJsonLoadError> {
        self.cjs_tracker
            .is_maybe_cjs_from_require(specifier, MediaType::from_specifier(specifier))
    }
}

#[derive(Debug)]
struct TaskRootCertStoreProvider(RootCertStore);

impl RootCertStoreProvider for TaskRootCertStoreProvider {
    fn get_or_try_init(&self) -> Result<&RootCertStore, JsErrorBox> {
        Ok(&self.0)
    }
}

pub(crate) fn run_npm_binary_blocking(
    project_dir: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    command_name: String,
    module_path: PathBuf,
    argv: Vec<String>,
) -> Result<i32, AnyError> {
    let runtime = crate::utils::tokio::build_task_runtime("npm binary")?;
    runtime.block_on(run_npm_binary(
        project_dir,
        config_file,
        lockfile,
        command_name,
        module_path,
        argv,
    ))
}

async fn run_npm_binary(
    project_dir: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    command_name: String,
    module_path: PathBuf,
    argv: Vec<String>,
) -> Result<i32, AnyError> {
    let project_dir = project_dir.canonicalize().map_err(project_state_error)?;
    let module_path = module_path.canonicalize().map_err(project_state_error)?;
    let main_module = Url::from_file_path(&module_path).map_err(|()| {
        project_state_error(deno_core::anyhow::anyhow!(
            "Could not convert npm binary path to file URL: {}",
            module_path.display()
        ))
    })?;
    let context = Rc::new(
        EmbedContext::new_with_options(
            project_dir.clone(),
            config_file,
            lockfile,
            project_embed_options(&project_dir),
        )
        .map_err(project_state_error)?,
    );
    let state = Arc::new(
        prepare_package_runtime(Rc::clone(&context), main_module.clone(), None)
            .await
            .map_err(project_state_error)?,
    );
    let resolver_factory = context.resolver_factory();
    let npm_resolver = resolver_factory.npm_resolver()?.clone();
    let sys = EmbedSys::default();
    let root_cert_store = get_root_cert_store(&sys, None, None, None)?;
    let module_loader_factory = TaskModuleLoaderFactory {
        state,
        cjs_tracker: resolver_factory.cjs_tracker()?.clone(),
        initial_cwd: project_dir.clone(),
    };
    let options = LibMainWorkerOptions {
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
        argv0: Some(command_name),
        node_debug: std::env::var("NODE_DEBUG").ok(),
        node_cluster_unique_id: std::env::var("NODE_UNIQUE_ID").ok(),
        node_cluster_sched_policy: std::env::var("NODE_CLUSTER_SCHED_POLICY").ok(),
        otel_config: Default::default(),
        origin_data_folder_path: None,
        seed: None,
        unsafely_ignore_certificate_errors: None,
        skip_op_registration: false,
        node_ipc_init: None,
        no_legacy_abort: false,
        startup_snapshot: None,
        residual_lazy_js_sources: &[],
        residual_lazy_esm_sources: &[],
        serve_port: None,
        serve_host: None,
        maybe_initial_cwd: Url::from_directory_path(&project_dir).ok(),
    };
    let factory = LibMainWorkerFactory::new(
        Arc::new(deno_runtime::deno_web::BlobStore::default()),
        None,
        None,
        Arc::new(FeatureChecker::default()),
        Arc::new(RealFs),
        None,
        None,
        Box::new(module_loader_factory),
        resolver_factory.node_resolver()?.clone(),
        create_npm_process_state_provider(&npm_resolver),
        resolver_factory.pkg_json_resolver().clone(),
        Arc::new(TaskRootCertStoreProvider(root_cert_store)),
        StorageKeyResolver::empty(),
        sys.clone(),
        options,
        LibWorkerFactoryRoots::default(),
        None,
    );
    let permission_parser = Arc::new(RuntimePermissionDescriptorParser::new(sys));
    let permissions = PermissionsContainer::allow_all(permission_parser);
    let mut worker = factory.create_main_worker(
        WorkerExecutionMode::Run,
        permissions,
        main_module,
        Vec::new(),
        Vec::new(),
    )?;
    worker.run().await.map_err(Into::into)
}
