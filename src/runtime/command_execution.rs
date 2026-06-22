use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command as ProcessCommand, Stdio as ProcessStdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use deno_core::ModuleSpecifier;
use deno_lib::args::npm_pkg_req_ref_to_binary_command;
use deno_resolver::workspace::{MappedResolution, ResolutionKind as WorkspaceResolutionKind};
use deno_runtime::deno_os::{WatcherExitHandle, WatcherExited};
use deno_semver::npm::NpmPackageReqReference;
use node_resolver::BinValue;
use tokio::sync::{oneshot, watch};

use crate::command::CommandSource;
use crate::embed::{EmbedContext, js_content_type_header_overrides, prepare_package_runtime};
use crate::runtime::package_worker::{self, PackageWorkerOptions};
use crate::runtime::{BoundPackageEnvironment, process_context};
use crate::types::error::BindingError;
use crate::utils::cancel_guard::Cancel;

type CommandResult<T = ()> = Result<T, BindingError>;

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
    pub(crate) cli_snapshot_eligible: Arc<dyn Fn() -> bool + Send + Sync>,
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

impl Cancel for CommandExecutionHandle {
    fn cancel(&self) {
        CommandExecutionHandle::cancel(self);
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
    let result = runtime.block_on(run_command(options, cancel_rx));
    runtime.shutdown_background();
    result
}

async fn run_command(
    options: CommandExecutionOptions,
    mut cancel_rx: watch::Receiver<bool>,
) -> CommandResult {
    let _context_lock = process_context::acquire_guard(&mut cancel_rx).await?;

    let command_cwd = resolve_command_cwd(&options.runtime_root, options.command.cwd())?;
    let _cwd_guard = CurrentDirGuard::change_to(&command_cwd)?;
    let _env_guard = EnvironmentGuard::apply(options.command.env());
    native_addon_host::ensure_symbols_visible()?;

    let context = options.package_environment.embed_context_rc()?;
    let (command_name, bin) =
        resolve_command(context.clone(), &command_cwd, options.command.name()).await?;
    let result = match bin {
        BinValue::Executable(path) if is_native_binary(&path) => {
            run_native_command(path, command_cwd, options.argv, &mut cancel_rx).await
        }
        BinValue::JsFile(path) | BinValue::Executable(path) => {
            run_js_command(
                context,
                command_cwd,
                command_name,
                path,
                options.argv,
                options.cli_snapshot_eligible.clone(),
                &mut cancel_rx,
            )
            .await
        }
    };
    result.map_err(map_windows_native_addon_error)
}

async fn resolve_command(
    context: std::rc::Rc<EmbedContext>,
    cwd: &Path,
    command: &str,
) -> CommandResult<(String, BinValue)> {
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
    Ok((
        if explicit_npm_specifier {
            npm_pkg_req_ref_to_binary_command(&package_ref).to_string()
        } else {
            command.to_string()
        },
        bin,
    ))
}

async fn run_js_command(
    context: std::rc::Rc<EmbedContext>,
    cwd: PathBuf,
    command_name: String,
    script_path: PathBuf,
    argv: Vec<String>,
    cli_snapshot_eligible: Arc<dyn Fn() -> bool + Send + Sync>,
    cancel_rx: &mut watch::Receiver<bool>,
) -> CommandResult {
    let main_module = ModuleSpecifier::from_file_path(&script_path).map_err(|()| {
        BindingError::runtime(format!(
            "Could not convert command entrypoint {} to a file URL",
            script_path.display()
        ))
    })?;
    let header_overrides = js_content_type_header_overrides(main_module.clone());
    let state = std::sync::Arc::new(
        prepare_package_runtime(context.clone(), main_module.clone(), None, header_overrides)
            .await
            .map_err(package_error)?,
    );
    let mut worker = package_worker::create_package_worker(
        state,
        context,
        cwd.clone(),
        main_module,
        PackageWorkerOptions {
            argv,
            argv0: Some(command_name),
            use_cli_snapshot: cli_snapshot_eligible(),
        },
    )?;

    let isolate = worker.js_runtime().v8_isolate().thread_safe_handle();
    worker
        .js_runtime()
        .op_state()
        .borrow_mut()
        .put(WatcherExitHandle(isolate.clone()));
    let (result, cancelled) = loop {
        let mut run = std::pin::pin!(worker.run());
        tokio::select! {
            result = &mut run => break (Some(result), false),
            changed = cancel_rx.changed() => {
                if process_context::watch_cancelled(changed, cancel_rx) {
                    isolate.terminate_execution();
                    break (None, true);
                }
            }
        }
    };
    if cancelled {
        worker
            .js_runtime()
            .v8_isolate()
            .cancel_terminate_execution();
        return Err(process_context::command_cancelled());
    }
    let result = result.expect("worker run future should complete");
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
        match result {
            Ok(code) => command_exit_result(code),
            Err(error) => Err(BindingError::runtime(error.to_string())),
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
                if process_context::watch_cancelled(changed, cancel_rx) {
                    terminate_native_command(&mut child).await;
                    return Err(process_context::command_cancelled());
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

fn package_error(error: impl std::fmt::Display) -> BindingError {
    BindingError::runtime(format!(
        "Environment dependencies are missing or out of date: {error}"
    ))
}

fn resolve_command_cwd(runtime_root: &Path, configured: Option<&Path>) -> CommandResult<PathBuf> {
    let path = match configured {
        Some(path) if path.is_absolute() => path.to_path_buf(),
        Some(path) => runtime_root.join(path),
        None => runtime_root.to_path_buf(),
    };
    let path = deno_path_util::strip_unc_prefix(path.canonicalize().map_err(|error| {
        BindingError::runtime(format!("Invalid command cwd {}: {error}", path.display()))
    })?);
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
                // SAFETY: command execution is serialized by PROCESS_CONTEXT_LOCK.
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

#[cfg(test)]
mod tests {
    use std::fs;

    use super::resolve_command_cwd;
    use crate::runtime::package_worker::package_worker_snapshot_options;

    #[test]
    fn cli_snapshot_options_enable_snapshot_and_skip_op_registration() {
        let options = package_worker_snapshot_options(true);
        assert!(options.startup_snapshot.is_some());
        assert!(!options.residual_lazy_js_sources.is_empty());
        assert!(!options.residual_lazy_esm_sources.is_empty());
        assert!(options.skip_op_registration);
    }

    #[test]
    fn cli_snapshot_options_disable_snapshot_and_op_skip_when_unavailable() {
        let options = package_worker_snapshot_options(false);
        assert!(options.startup_snapshot.is_none());
        assert!(options.residual_lazy_js_sources.is_empty());
        assert!(options.residual_lazy_esm_sources.is_empty());
        assert!(!options.skip_op_registration);
    }

    #[test]
    fn resolves_relative_command_cwd_against_runtime_root() {
        let root = tempfile::tempdir().expect("temp dir should be created");
        let frontend = root.path().join("frontend");
        fs::create_dir(&frontend).expect("frontend dir should be created");

        let resolved = resolve_command_cwd(root.path(), Some("frontend".as_ref()))
            .expect("command cwd should resolve");

        let expected = deno_path_util::strip_unc_prefix(
            frontend
                .canonicalize()
                .expect("frontend should canonicalize"),
        );

        assert_eq!(resolved, expected);
    }

    #[cfg(windows)]
    #[test]
    fn strips_windows_verbatim_prefix_from_resolved_command_cwd() {
        let root = tempfile::tempdir().expect("temp dir should be created");

        let resolved = resolve_command_cwd(root.path(), None).expect("command cwd should resolve");
        let resolved = resolved.to_string_lossy();

        assert!(!resolved.starts_with(r"\\?\"));
    }
}
