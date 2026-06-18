use std::borrow::Cow;
use std::collections::HashMap;
use std::ffi::{OsStr, OsString};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::Arc;

use deno_cache_dir::file_fetcher::MemoryFiles;
use deno_core::error::AnyError;
use deno_core::{FastString, ModuleSpecifier};
use deno_error::JsErrorBox;
use deno_lib::args::get_root_cert_store;
use deno_lib::npm::create_npm_process_state_provider;
use deno_lib::worker::{
    CreateModuleLoaderResult, LibMainWorkerFactory, LibMainWorkerOptions, LibWorkerFactoryRoots,
    ModuleLoaderFactory, StorageKeyResolver,
};
use deno_media_type::MediaType;
use deno_resolver::cjs::CjsTrackerRc;
use deno_resolver::npm::{DenoInNpmPackageChecker, NpmResolver};
use deno_runtime::deno_fs::RealFs;
use deno_runtime::deno_io::{PipeRead, Stdio, StdioPipe, pipe};
use deno_runtime::deno_node::NodeRequireLoader;
use deno_runtime::deno_permissions::{Permissions, PermissionsContainer};
use deno_runtime::deno_tls::RootCertStoreProvider;
use deno_runtime::deno_tls::rustls::RootCertStore;
use deno_runtime::deno_web::{BlobStore, BlobStoreTrait};
use deno_runtime::permissions::RuntimePermissionDescriptorParser;
use deno_runtime::{FeatureChecker, WorkerExecutionMode, WorkerLogLevel};
use deno_task_shell::ShellPipeWriter;
use node_resolver::errors::PackageJsonLoadError;
use once_cell::sync::OnceCell;
use tokio::task::JoinHandle;

use crate::embed::sys::EmbedSys;
use crate::embed::{
    PackageRuntimeState, js_content_type_header_overrides, prepare_package_runtime,
};
use crate::packages::ProjectPackageEnvironment;
use crate::runtime::module_loader::PackageAwareModuleLoader;

type StdioForwarder = JoinHandle<Result<(), AnyError>>;
type WorkerStdio = (Stdio, Vec<StdioForwarder>);

static TASK_NPM_BIN_CWD_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

pub(crate) struct TaskNpmBinOptions {
    pub(crate) project_cwd: PathBuf,
    pub(crate) task_cwd: PathBuf,
    pub(crate) command_name: String,
    pub(crate) script_path: PathBuf,
    pub(crate) argv: Vec<String>,
    pub(crate) env_vars: HashMap<OsString, OsString>,
    pub(crate) stdout: ShellPipeWriter,
    pub(crate) stderr: ShellPipeWriter,
}

pub(crate) async fn run_task_npm_bin(options: TaskNpmBinOptions) -> i32 {
    let mut error_stderr = options.stderr.clone();
    match run_task_npm_bin_inner(options).await {
        Ok(exit_code) => exit_code,
        Err(error) => {
            let _ = error_stderr.write_line(&format!("{error}"));
            1
        }
    }
}

async fn run_task_npm_bin_inner(options: TaskNpmBinOptions) -> Result<i32, AnyError> {
    let TaskNpmBinOptions {
        project_cwd,
        task_cwd,
        command_name,
        script_path,
        argv,
        env_vars,
        stdout,
        stderr,
    } = options;
    let _cwd_lock = TASK_NPM_BIN_CWD_LOCK.lock().await;
    let _cwd_guard = CurrentDirGuard::change_to(&task_cwd)?;
    let project_env = ProjectPackageEnvironment::from_folder(project_cwd.clone(), None, false)?
        .ok_or_else(|| {
            deno_core::anyhow::anyhow!(
                "No belgie package dependencies found in {}",
                project_cwd.join("pyproject.toml").display()
            )
        })?;
    let context = project_env.embed_context()?;
    let main_module = ModuleSpecifier::from_file_path(&script_path).map_err(|()| {
        deno_core::anyhow::anyhow!("Could not convert {} to file URL", script_path.display())
    })?;
    let resolver_factory = context.resolver_factory();
    let npm_resolver = resolver_factory.npm_resolver()?;
    let node_resolver = resolver_factory.node_resolver()?.clone();
    let pkg_json_resolver = resolver_factory.pkg_json_resolver().clone();
    let cjs_tracker = resolver_factory.cjs_tracker()?.clone();
    let memory_files = context.memory_files().clone();
    let state = Arc::new(
        prepare_package_runtime(
            context.clone(),
            main_module.clone(),
            None,
            js_content_type_header_overrides(main_module.clone()),
        )
        .await?,
    );
    let module_loader_factory = Box::new(BelgieModuleLoaderFactory {
        state,
        initial_cwd: task_cwd.clone(),
        cjs_tracker,
        npm_resolver: npm_resolver.clone(),
        memory_files,
    });
    let permissions = PermissionsContainer::new(
        Arc::new(RuntimePermissionDescriptorParser::new(EmbedSys::default())),
        Permissions::allow_all(),
    );
    let root_cert_store_provider = Arc::new(BelgieRootCertStoreProvider::default());
    let (stdio, stdio_forwarders) = worker_stdio(stdout, stderr)?;
    let mut worker = LibMainWorkerFactory::new(
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
        pkg_json_resolver,
        root_cert_store_provider,
        StorageKeyResolver::empty(),
        EmbedSys::default(),
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
            argv0: Some(command_name),
            node_debug: env_var_string(&env_vars, "NODE_DEBUG"),
            node_cluster_unique_id: env_var_string(&env_vars, "NODE_UNIQUE_ID"),
            node_cluster_sched_policy: env_var_string(&env_vars, "NODE_CLUSTER_SCHED_POLICY"),
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
            maybe_initial_cwd: ModuleSpecifier::from_directory_path(&task_cwd).ok(),
        },
        LibWorkerFactoryRoots::default(),
        None,
    )
    .create_custom_worker(
        WorkerExecutionMode::Run,
        main_module,
        Vec::new(),
        Vec::new(),
        permissions,
        Vec::new(),
        stdio,
        None,
    )?;

    let result = worker.run().await.map_err(AnyError::from);
    drop(worker);
    wait_stdio_forwarders(stdio_forwarders).await?;
    result
}

fn env_var_string(env_vars: &HashMap<OsString, OsString>, name: &str) -> Option<String> {
    let name = if cfg!(windows) {
        OsStr::new(name).to_ascii_uppercase()
    } else {
        OsString::from(name)
    };
    env_vars
        .get(&name)
        .and_then(|value| value.clone().into_string().ok())
}

fn worker_stdio(stdout: ShellPipeWriter, stderr: ShellPipeWriter) -> Result<WorkerStdio, AnyError> {
    let (stdout_read, stdout_write) = pipe()?;
    let (stderr_read, stderr_write) = pipe()?;
    let stdio = Stdio {
        stdin: StdioPipe::inherit(),
        stdout: StdioPipe::file(std::fs::File::from(stdout_write)),
        stderr: StdioPipe::file(std::fs::File::from(stderr_write)),
    };
    Ok((
        stdio,
        vec![
            forward_stdio_pipe(stdout_read, stdout),
            forward_stdio_pipe(stderr_read, stderr),
        ],
    ))
}

fn forward_stdio_pipe(mut reader: PipeRead, mut writer: ShellPipeWriter) -> StdioForwarder {
    tokio::task::spawn_blocking(move || {
        let mut buffer = [0; 8192];
        loop {
            let read = reader.read(&mut buffer)?;
            if read == 0 {
                break;
            }
            writer.write_all(&buffer[..read])?;
        }
        Ok(())
    })
}

async fn wait_stdio_forwarders(forwarders: Vec<StdioForwarder>) -> Result<(), AnyError> {
    for forwarder in forwarders {
        forwarder.await??;
    }
    Ok(())
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
            return Ok(String::from_utf8_lossy(&file.source).into_owned().into());
        }
        let bytes = std::fs::read(path).map_err(JsErrorBox::from_err)?;
        Ok(String::from_utf8_lossy(&bytes).into_owned().into())
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
        let is_managed_global_cache = self
            .npm_resolver
            .as_managed()
            .filter(|resolver| resolver.root_node_modules_path().is_none())
            .map(|resolver| resolver.global_cache_root_path())
            .filter(|global_cache_path| from.starts_with(global_cache_path))
            .is_some();
        if is_managed_global_cache {
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

struct CurrentDirGuard {
    previous: PathBuf,
}

impl CurrentDirGuard {
    fn change_to(path: &Path) -> Result<Self, AnyError> {
        let previous = std::env::current_dir()?;
        std::env::set_current_dir(path)?;
        Ok(Self { previous })
    }
}

impl Drop for CurrentDirGuard {
    fn drop(&mut self) {
        let _ = std::env::set_current_dir(&self.previous);
    }
}
