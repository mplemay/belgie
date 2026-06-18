use std::borrow::Cow;
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command as ProcessCommand, Stdio as ProcessStdio};
use std::rc::Rc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use deno_cache_dir::file_fetcher::MemoryFiles;
use deno_core::{FastString, ModuleSpecifier};
use deno_error::JsErrorBox;
use deno_lib::args::{get_root_cert_store, npm_pkg_req_ref_to_binary_command};
use deno_lib::npm::create_npm_process_state_provider;
use deno_lib::worker::{
    CreateModuleLoaderResult, LibMainWorkerFactory, LibMainWorkerOptions, LibWorkerFactoryRoots,
    ModuleLoaderFactory, StorageKeyResolver,
};
use deno_media_type::MediaType;
use deno_resolver::cjs::CjsTrackerRc;
use deno_resolver::npm::{DenoInNpmPackageChecker, NpmResolver};
use deno_resolver::workspace::{MappedResolution, ResolutionKind as WorkspaceResolutionKind};
use deno_runtime::deno_fs::RealFs;
use deno_runtime::deno_node::NodeRequireLoader;
use deno_runtime::deno_os::{WatcherExitHandle, WatcherExited};
use deno_runtime::deno_permissions::{Permissions, PermissionsContainer};
use deno_runtime::deno_tls::RootCertStoreProvider;
use deno_runtime::deno_tls::rustls::RootCertStore;
use deno_runtime::deno_web::{BlobStore, BlobStoreTrait};
use deno_runtime::permissions::RuntimePermissionDescriptorParser;
use deno_runtime::{FeatureChecker, WorkerExecutionMode, WorkerLogLevel};
use deno_semver::npm::NpmPackageReqReference;
use node_resolver::BinValue;
use node_resolver::errors::PackageJsonLoadError;
use once_cell::sync::OnceCell;
use tokio::sync::{oneshot, watch};

use crate::command::CommandSource;
use crate::embed::sys::EmbedSys;
use crate::embed::{
    EmbedContext, PackageRuntimeState, js_content_type_header_overrides, prepare_package_runtime,
};
use crate::packages::project_state_error;
use crate::runtime::BoundPackageEnvironment;
use crate::runtime::module_loader::PackageAwareModuleLoader;
use crate::types::error::BindingError;

type CommandResult<T = ()> = Result<T, BindingError>;

static COMMAND_CONTEXT_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[derive(Clone, Debug)]
pub(crate) struct CommandExecutionHandle {
    inner: Arc<CommandExecutionHandleInner>,
}

#[derive(Debug)]
struct CommandExecutionHandleInner {
    cancel: watch::Sender<bool>,
    response: Mutex<Option<oneshot::Receiver<CommandResult>>>,
    join_handle: Mutex<Option<thread::JoinHandle<()>>>,
}

pub(crate) struct CommandExecutionOptions {
    pub(crate) package_environment: BoundPackageEnvironment,
    pub(crate) runtime_root: PathBuf,
    pub(crate) command: CommandSource,
    pub(crate) argv: Vec<String>,
}

impl CommandExecutionHandle {
    pub(crate) fn spawn(options: CommandExecutionOptions) -> Self {
        let (cancel, cancel_rx) = watch::channel(false);
        let (respond_to, response) = oneshot::channel();
        let join_handle = thread::spawn(move || {
            let result = run_command_thread(options, cancel_rx);
            let _ = respond_to.send(result);
        });
        Self {
            inner: Arc::new(CommandExecutionHandleInner {
                cancel,
                response: Mutex::new(Some(response)),
                join_handle: Mutex::new(Some(join_handle)),
            }),
        }
    }

    pub(crate) fn cancel(&self) {
        let _ = self.inner.cancel.send(true);
    }

    pub(crate) fn wait_blocking(&self) -> CommandResult {
        let response = self.take_response()?;
        response
            .blocking_recv()
            .map_err(|_| BindingError::runtime("Command worker stopped unexpectedly"))?
    }

    pub(crate) async fn wait_async(&self) -> CommandResult {
        let response = self.take_response()?;
        response
            .await
            .map_err(|_| BindingError::runtime("Command worker stopped unexpectedly"))?
    }

    pub(crate) fn close_blocking(&self) -> CommandResult {
        self.cancel();
        let join_handle = self
            .inner
            .join_handle
            .lock()
            .expect("command worker join handle lock should not be poisoned")
            .take();
        if let Some(join_handle) = join_handle {
            join_handle
                .join()
                .map_err(|_| BindingError::runtime("Command worker panicked"))?;
        }
        Ok(())
    }

    fn take_response(&self) -> Result<oneshot::Receiver<CommandResult>, BindingError> {
        self.inner
            .response
            .lock()
            .expect("command response lock should not be poisoned")
            .take()
            .ok_or_else(|| BindingError::runtime("Command runner may only be invoked once"))
    }
}

impl Drop for CommandExecutionHandleInner {
    fn drop(&mut self) {
        let _ = self.cancel.send(true);
        if let Some(join_handle) = self
            .join_handle
            .lock()
            .expect("command worker join handle lock should not be poisoned")
            .take()
        {
            let _ = join_handle.join();
        }
    }
}

fn run_command_thread(
    options: CommandExecutionOptions,
    cancel_rx: watch::Receiver<bool>,
) -> CommandResult {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|error| {
            BindingError::runtime(format!("Creating command runtime failed: {error}"))
        })?;
    runtime.block_on(run_command(options, cancel_rx))
}

async fn run_command(
    options: CommandExecutionOptions,
    mut cancel_rx: watch::Receiver<bool>,
) -> CommandResult {
    if *cancel_rx.borrow() {
        return Err(command_cancelled());
    }
    let _context_lock = loop {
        tokio::select! {
            guard = COMMAND_CONTEXT_LOCK.lock() => break guard,
            changed = cancel_rx.changed() => {
                if changed.is_err() || *cancel_rx.borrow() {
                    return Err(command_cancelled());
                }
            }
        }
    };
    if *cancel_rx.borrow() {
        return Err(command_cancelled());
    }

    let command_cwd = resolve_command_cwd(&options.runtime_root, options.command.cwd())?;
    let _cwd_guard = CurrentDirGuard::change_to(&command_cwd)?;
    let _env_guard = EnvironmentGuard::apply(options.command.env());
    native_addon_host::ensure_symbols_visible()?;

    let context = embed_context_rc(&options.package_environment)?;
    let resolved = resolve_command(context.clone(), &command_cwd, options.command.name()).await?;
    let command_name = resolved.command_name;
    let result = match resolved.bin {
        BinValue::JsFile(path) => {
            run_js_command(
                context,
                command_cwd,
                command_name,
                path,
                options.argv,
                &mut cancel_rx,
            )
            .await
        }
        BinValue::Executable(path) if is_native_binary(&path) => {
            run_native_command(path, command_cwd, options.argv, &mut cancel_rx).await
        }
        BinValue::Executable(path) => {
            run_js_command(
                context,
                command_cwd,
                command_name,
                path,
                options.argv,
                &mut cancel_rx,
            )
            .await
        }
    };
    result.map_err(map_windows_native_addon_error)
}

struct ResolvedCommand {
    command_name: String,
    bin: BinValue,
}

async fn resolve_command(
    context: Rc<EmbedContext>,
    cwd: &Path,
    command: &str,
) -> CommandResult<ResolvedCommand> {
    context
        .npm_installer_factory()
        .initialize_npm_resolution_if_managed()
        .await
        .map_err(package_error)?;
    let resolver_factory = context.resolver_factory();
    let cwd_url = deno_path_util::url_from_directory_path(cwd).map_err(package_error)?;
    let explicit_npm_specifier = command.starts_with("npm:");
    let specifier = if explicit_npm_specifier {
        ModuleSpecifier::parse(command).map_err(package_error)?
    } else {
        match resolver_factory
            .workspace_resolver()
            .await
            .map_err(package_error)?
            .resolve(command, &cwd_url, WorkspaceResolutionKind::Execution)
            .map_err(package_error)?
        {
            MappedResolution::Normal { specifier, .. } => specifier,
            resolution => {
                return Err(BindingError::runtime(format!(
                    "Command {command:?} did not resolve to an npm package: {resolution:?}"
                )));
            }
        }
    };
    let package_ref = NpmPackageReqReference::from_specifier(&specifier).map_err(|_| {
        BindingError::runtime(format!(
            "Command {command:?} resolved to {specifier}, but only npm package commands are supported"
        ))
    })?;
    let npm_resolver = resolver_factory.npm_resolver().map_err(package_error)?;
    let package_folder = npm_resolver
        .resolve_pkg_folder_from_deno_module_req(package_ref.req(), &cwd_url)
        .map_err(package_error)?;
    let node_resolver = resolver_factory.node_resolver().map_err(package_error)?;
    let bin = node_resolver
        .resolve_binary_export(&package_folder, package_ref.sub_path())
        .map_err(package_error)?;
    Ok(ResolvedCommand {
        command_name: if explicit_npm_specifier {
            npm_pkg_req_ref_to_binary_command(&package_ref).to_string()
        } else {
            command.to_string()
        },
        bin,
    })
}

async fn run_js_command(
    context: Rc<EmbedContext>,
    cwd: PathBuf,
    command_name: String,
    script_path: PathBuf,
    argv: Vec<String>,
    cancel_rx: &mut watch::Receiver<bool>,
) -> CommandResult {
    let main_module = ModuleSpecifier::from_file_path(&script_path).map_err(|()| {
        BindingError::runtime(format!(
            "Could not convert command entrypoint {} to a file URL",
            script_path.display()
        ))
    })?;
    let resolver_factory = context.resolver_factory();
    let npm_resolver = resolver_factory.npm_resolver().map_err(package_error)?;
    let node_resolver = resolver_factory
        .node_resolver()
        .map_err(package_error)?
        .clone();
    let state = Arc::new(
        prepare_package_runtime(
            context.clone(),
            main_module.clone(),
            None,
            js_content_type_header_overrides(main_module.clone()),
        )
        .await
        .map_err(package_error)?,
    );
    let module_loader_factory = Box::new(BelgieModuleLoaderFactory {
        state,
        initial_cwd: cwd.clone(),
        cjs_tracker: resolver_factory
            .cjs_tracker()
            .map_err(package_error)?
            .clone(),
        npm_resolver: npm_resolver.clone(),
        memory_files: context.memory_files().clone(),
    });
    let permissions = PermissionsContainer::new(
        Arc::new(RuntimePermissionDescriptorParser::new(EmbedSys::default())),
        Permissions::allow_all(),
    );
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
        resolver_factory.pkg_json_resolver().clone(),
        Arc::new(BelgieRootCertStoreProvider::default()),
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
            maybe_initial_cwd: ModuleSpecifier::from_directory_path(&cwd).ok(),
        },
        LibWorkerFactoryRoots::default(),
        None,
    )
    .create_main_worker(
        WorkerExecutionMode::Run,
        permissions,
        main_module,
        Vec::new(),
        Vec::new(),
    )
    .map_err(|error| BindingError::runtime(error.to_string()))?;

    let isolate = worker.js_runtime().v8_isolate().thread_safe_handle();
    worker
        .js_runtime()
        .op_state()
        .borrow_mut()
        .put(WatcherExitHandle(isolate.clone()));
    enum WorkerOutcome {
        Completed(Result<i32, deno_core::error::CoreError>),
        Cancelled,
    }
    let outcome = {
        let mut run = std::pin::pin!(worker.run());
        tokio::select! {
            result = &mut run => WorkerOutcome::Completed(result),
            changed = cancel_rx.changed() => {
                if changed.is_err() || *cancel_rx.borrow() {
                    isolate.terminate_execution();
                }
                let _ = run.await;
                WorkerOutcome::Cancelled
            }
        }
    };
    match outcome {
        WorkerOutcome::Completed(result) => {
            let exited = worker
                .js_runtime()
                .op_state()
                .borrow()
                .has::<WatcherExited>();
            if exited {
                worker
                    .js_runtime()
                    .v8_isolate()
                    .cancel_terminate_execution();
                command_exit_result(worker.exit_code())
            } else {
                command_exit_result(
                    result.map_err(|error| BindingError::runtime(error.to_string()))?,
                )
            }
        }
        WorkerOutcome::Cancelled => {
            worker
                .js_runtime()
                .v8_isolate()
                .cancel_terminate_execution();
            Err(command_cancelled())
        }
    }
}

async fn run_native_command(
    path: PathBuf,
    cwd: PathBuf,
    argv: Vec<String>,
    cancel_rx: &mut watch::Receiver<bool>,
) -> CommandResult {
    let mut command = ProcessCommand::new(&path);
    command
        .args(argv)
        .current_dir(cwd)
        .stdin(ProcessStdio::inherit())
        .stdout(ProcessStdio::inherit())
        .stderr(ProcessStdio::inherit());
    configure_native_command(&mut command);
    let mut child = command.spawn().map_err(|error| {
        BindingError::runtime(format!("Failed to spawn {}: {error}", path.display()))
    })?;
    loop {
        if let Some(status) = child.try_wait().map_err(|error| {
            BindingError::runtime(format!("Waiting for command failed: {error}"))
        })? {
            return command_exit_result(status.code().unwrap_or(1));
        }
        tokio::select! {
            changed = cancel_rx.changed() => {
                if changed.is_err() || *cancel_rx.borrow() {
                    terminate_native_command(&mut child).await;
                    return Err(command_cancelled());
                }
            }
            () = tokio::time::sleep(Duration::from_millis(25)) => {}
        }
    }
}

#[cfg(unix)]
fn configure_native_command(command: &mut ProcessCommand) {
    use std::os::unix::process::CommandExt;

    // SAFETY: this runs after fork and only invokes the async-signal-safe setpgid syscall.
    unsafe {
        command.pre_exec(|| {
            if libc::setpgid(0, 0) == 0 {
                Ok(())
            } else {
                Err(std::io::Error::last_os_error())
            }
        });
    }
}

#[cfg(not(unix))]
fn configure_native_command(_command: &mut ProcessCommand) {}

#[cfg(unix)]
async fn terminate_native_command(child: &mut std::process::Child) {
    let process_group = child.id() as i32;
    // SAFETY: the child was placed in a process group whose id matches its pid.
    unsafe {
        libc::kill(-process_group, libc::SIGTERM);
    }
    for _ in 0..8 {
        if child.try_wait().ok().flatten().is_some() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    // SAFETY: the process group id was obtained from the spawned child.
    unsafe {
        libc::kill(-process_group, libc::SIGKILL);
    }
    let _ = child.wait();
}

#[cfg(not(unix))]
async fn terminate_native_command(child: &mut std::process::Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn command_exit_result(exit_code: i32) -> CommandResult {
    if exit_code == 0 {
        Ok(())
    } else {
        Err(BindingError::runtime(format!(
            "Command exited with status {exit_code}"
        )))
    }
}

fn command_cancelled() -> BindingError {
    BindingError::runtime("Command was cancelled")
}

fn package_error(error: impl std::fmt::Display) -> BindingError {
    BindingError::runtime(project_state_error(error).to_string())
}

fn resolve_command_cwd(runtime_root: &Path, configured: Option<&Path>) -> CommandResult<PathBuf> {
    let path = match configured {
        Some(path) if path.is_absolute() => path.to_path_buf(),
        Some(path) => runtime_root.join(path),
        None => runtime_root.to_path_buf(),
    };
    let path = path.canonicalize().map_err(|error| {
        BindingError::runtime(format!("Invalid command cwd {}: {error}", path.display()))
    })?;
    if !path.is_dir() {
        return Err(BindingError::runtime(format!(
            "Command cwd is not a directory: {}",
            path.display()
        )));
    }
    Ok(path)
}

fn is_native_binary(path: &Path) -> bool {
    let Ok(mut file) = File::open(path) else {
        return false;
    };
    let mut bytes = [0; 4];
    file.read_exact(&mut bytes).is_ok() && node_resolver::is_binary(&bytes)
}

fn embed_context_rc(
    package_environment: &BoundPackageEnvironment,
) -> Result<Rc<EmbedContext>, BindingError> {
    match package_environment {
        BoundPackageEnvironment::Isolated(environment) => environment
            .embed_context()
            .map_err(|error| BindingError::runtime(error.to_string())),
        BoundPackageEnvironment::Project(environment) => environment
            .embed_context()
            .map_err(|error| BindingError::runtime(error.to_string())),
    }
}

fn map_windows_native_addon_error(error: BindingError) -> BindingError {
    #[cfg(windows)]
    {
        let message = error.message();
        let lowercase = message.to_ascii_lowercase();
        if lowercase.contains("node-api")
            || lowercase.contains("napi")
            || lowercase.contains(".node")
            || lowercase.contains("loadlibrary")
        {
            return BindingError::runtime(format!(
                "Native Node-API package commands are not supported by Belgie on Windows without a separate executable host: {message}"
            ));
        }
    }
    error
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

struct CurrentDirGuard {
    previous: PathBuf,
}

impl CurrentDirGuard {
    fn change_to(path: &Path) -> Result<Self, BindingError> {
        let previous = std::env::current_dir()
            .map_err(|error| BindingError::runtime(format!("Reading cwd failed: {error}")))?;
        std::env::set_current_dir(path).map_err(|error| {
            BindingError::runtime(format!(
                "Changing cwd to {} failed: {error}",
                path.display()
            ))
        })?;
        Ok(Self { previous })
    }
}

impl Drop for CurrentDirGuard {
    fn drop(&mut self) {
        let _ = std::env::set_current_dir(&self.previous);
    }
}

struct EnvironmentGuard {
    previous: Vec<(OsString, Option<OsString>)>,
}

impl EnvironmentGuard {
    fn apply(values: &BTreeMap<String, String>) -> Self {
        let previous = values
            .iter()
            .map(|(key, value)| {
                let key = OsString::from(key);
                let previous = std::env::var_os(&key);
                // SAFETY: command execution is serialized by COMMAND_CONTEXT_LOCK.
                unsafe { std::env::set_var(&key, value) };
                (key, previous)
            })
            .collect();
        Self { previous }
    }
}

impl Drop for EnvironmentGuard {
    fn drop(&mut self) {
        for (key, value) in self.previous.drain(..).rev() {
            // SAFETY: command execution remains serialized until this guard drops.
            unsafe {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        }
    }
}

#[cfg(unix)]
mod native_addon_host {
    use std::ffi::CStr;
    use std::mem::MaybeUninit;
    use std::os::raw::c_void;
    use std::sync::OnceLock;

    use crate::types::error::BindingError;

    static PROMOTION_RESULT: OnceLock<Result<(), String>> = OnceLock::new();

    pub(super) fn ensure_symbols_visible() -> Result<(), BindingError> {
        match PROMOTION_RESULT.get_or_init(promote_current_library) {
            Ok(()) => Ok(()),
            Err(message) => Err(BindingError::runtime(message.clone())),
        }
    }

    fn promote_current_library() -> Result<(), String> {
        let mut info = MaybeUninit::<libc::Dl_info>::zeroed();
        let symbol = promote_current_library as *const () as *const c_void;
        // SAFETY: dladdr receives a valid function address and output pointer.
        if unsafe { libc::dladdr(symbol, info.as_mut_ptr()) } == 0 {
            return Err(dlerror_or(
                "Could not locate the loaded Belgie runtime library",
            ));
        }
        // SAFETY: dladdr initialized info after returning non-zero.
        let info = unsafe { info.assume_init() };
        if info.dli_fname.is_null() {
            return Err("Could not locate the loaded Belgie runtime library path".to_string());
        }
        // SAFETY: the path came from dladdr and identifies the already-loaded extension.
        unsafe {
            libc::dlerror();
            let handle = libc::dlopen(
                info.dli_fname,
                libc::RTLD_LAZY | libc::RTLD_NOLOAD | libc::RTLD_GLOBAL,
            );
            if handle.is_null() {
                let path = CStr::from_ptr(info.dli_fname).to_string_lossy();
                return Err(format!(
                    "Could not make Belgie runtime symbols visible for native npm addons at {path}: {}",
                    dlerror_or("dlopen failed"),
                ));
            }
        }
        Ok(())
    }

    fn dlerror_or(default: &str) -> String {
        // SAFETY: dlerror returns either null or a valid C error string.
        let error = unsafe { libc::dlerror() };
        if error.is_null() {
            default.to_string()
        } else {
            // SAFETY: non-null dlerror pointers reference a null-terminated string.
            unsafe { CStr::from_ptr(error) }
                .to_string_lossy()
                .into_owned()
        }
    }
}

#[cfg(not(unix))]
mod native_addon_host {
    use crate::types::error::BindingError;

    pub(super) fn ensure_symbols_visible() -> Result<(), BindingError> {
        Ok(())
    }
}
