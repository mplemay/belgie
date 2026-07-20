use std::{
    path::PathBuf,
    rc::Rc,
    sync::{Arc, Mutex, mpsc},
    thread,
};

use deno_core::{
    ExternalOpsTracker, JsRuntime, ModuleId, ModuleSpecifier, PollEventLoopOptions, RuntimeOptions,
    error::CoreError, v8,
};
use deno_lib::worker::{LibMainWorker, LibWorkerFactoryRoots};
#[cfg(test)]
use deno_runtime::tokio_util::create_and_run_current_thread;
use deno_runtime::tokio_util::create_basic_runtime;
use tokio::sync::{Notify, oneshot};

use crate::{
    embed::{init::spawn_v8_worker, runtime::content_type_header_overrides},
    runtime::{module_loader, package_worker, process_context},
    types::{error::BindingError, runner::RunnerArguments, value::PyJsValue},
    utils::cancel_guard::Cancel,
};

use super::BoundRuntime;
use crate::runtime::bound_runtime::BoundPackageEnvironment;

type ExecutionResult<T> = Result<T, BindingError>;

const RENDER_CONTEXT_SYMBOL: &str = "@belgie/render/context";
const SAFE_PROCESS_ENVIRONMENT: [(&str, &str); 3] = [
    ("APPVEYOR", "1"),
    ("NODE_ENV", "production"),
    ("TERM", "dumb"),
];

#[derive(Clone, Debug)]
pub(crate) struct DenoExecutionHandle {
    inner: Arc<DenoExecutionHandleInner>,
}

#[derive(Debug)]
struct DenoExecutionHandleInner {
    sender: mpsc::Sender<ExecutionCommand>,
    isolate_handle: Arc<Mutex<Option<v8::IsolateHandle>>>,
    shutdown: Arc<Notify>,
    join_handle: Mutex<Option<thread::JoinHandle<()>>>,
}

#[derive(Debug)]
enum ExecutionCommand {
    Invoke {
        arguments: RunnerArguments,
        respond_to: oneshot::Sender<ExecutionResult<PyJsValue>>,
    },
    Shutdown,
}

impl DenoExecutionHandle {
    pub(crate) fn new(bound: BoundRuntime, worker_factory_roots: LibWorkerFactoryRoots) -> Self {
        let (sender, receiver) = mpsc::channel();
        let isolate_handle = Arc::new(Mutex::new(None));
        let worker_isolate_handle = isolate_handle.clone();
        let shutdown = Arc::new(Notify::new());
        let worker_shutdown = shutdown.clone();
        let join_handle = spawn_v8_worker(move || {
            run_worker_thread(
                bound,
                worker_factory_roots,
                receiver,
                worker_isolate_handle,
                worker_shutdown,
            )
        });
        Self {
            inner: Arc::new(DenoExecutionHandleInner {
                sender,
                isolate_handle,
                shutdown,
                join_handle: Mutex::new(Some(join_handle)),
            }),
        }
    }

    pub(crate) fn is_closed(&self) -> bool {
        self.inner
            .join_handle
            .lock()
            .expect("execution worker join handle lock should not be poisoned")
            .is_none()
    }

    pub(crate) fn close_blocking(&self) -> ExecutionResult<()> {
        let join_handle = self
            .inner
            .join_handle
            .lock()
            .expect("execution worker join handle lock should not be poisoned")
            .take();
        let Some(join_handle) = join_handle else {
            return Ok(());
        };

        self.cancel();
        join_handle
            .join()
            .map_err(|_| BindingError::runtime("Deno execution worker panicked"))?;
        Ok(())
    }

    pub(crate) fn cancel(&self) {
        self.inner.signal_shutdown();
    }

    pub(crate) fn invoke_blocking(&self, arguments: RunnerArguments) -> ExecutionResult<PyJsValue> {
        if self.is_closed() {
            return Err(BindingError::runtime("Deno execution runner is closed"));
        }
        let (respond_to, response) = oneshot::channel();
        self.inner
            .sender
            .send(ExecutionCommand::Invoke {
                arguments,
                respond_to,
            })
            .map_err(|_| BindingError::runtime("Deno execution worker is not available"))?;
        response
            .blocking_recv()
            .map_err(|_| BindingError::runtime("Deno execution worker stopped unexpectedly"))?
    }

    pub(crate) async fn invoke_async(
        &self,
        arguments: RunnerArguments,
    ) -> ExecutionResult<PyJsValue> {
        if self.is_closed() {
            return Err(BindingError::runtime("Deno execution runner is closed"));
        }
        let (respond_to, response) = oneshot::channel();
        self.inner
            .sender
            .send(ExecutionCommand::Invoke {
                arguments,
                respond_to,
            })
            .map_err(|_| BindingError::runtime("Deno execution worker is not available"))?;
        response
            .await
            .map_err(|_| BindingError::runtime("Deno execution worker stopped unexpectedly"))?
    }
}

impl Cancel for DenoExecutionHandle {
    fn cancel(&self) {
        DenoExecutionHandle::cancel(self);
    }
}

impl DenoExecutionHandleInner {
    fn signal_shutdown(&self) {
        if let Some(handle) = self
            .isolate_handle
            .lock()
            .expect("execution isolate handle lock should not be poisoned")
            .as_ref()
        {
            handle.terminate_execution();
        }
        self.shutdown.notify_one();
        let _ = self.sender.send(ExecutionCommand::Shutdown);
    }
}

impl Drop for DenoExecutionHandleInner {
    fn drop(&mut self) {
        self.signal_shutdown();
        if let Some(join_handle) = self
            .join_handle
            .lock()
            .expect("execution worker join handle lock should not be poisoned")
            .take()
        {
            let _ = join_handle.join();
        }
    }
}

fn run_worker_thread(
    bound: BoundRuntime,
    worker_factory_roots: LibWorkerFactoryRoots,
    receiver: mpsc::Receiver<ExecutionCommand>,
    isolate_handle: Arc<Mutex<Option<v8::IsolateHandle>>>,
    shutdown: Arc<Notify>,
) {
    let runtime = create_basic_runtime();
    let mut context = {
        let _process_context = process_context::blocking_guard();
        match runtime.block_on(DenoExecutionContext::new(bound, &worker_factory_roots)) {
            Ok(context) => context,
            Err(error) => {
                while let Ok(command) = receiver.recv() {
                    match command {
                        ExecutionCommand::Invoke { respond_to, .. } => {
                            let _ = respond_to.send(Err(error.clone()));
                        }
                        ExecutionCommand::Shutdown => break,
                    }
                }
                return;
            }
        }
    };
    *isolate_handle
        .lock()
        .expect("execution isolate handle lock should not be poisoned") =
        Some(context.js_runtime().v8_isolate().thread_safe_handle());

    while let Ok(command) = receiver.recv() {
        match command {
            ExecutionCommand::Invoke {
                arguments,
                respond_to,
            } => {
                let _process_context = process_context::blocking_guard();
                let result = runtime.block_on(async {
                    tokio::select! {
                        result = context.invoke(arguments) => result,
                        () = shutdown.notified() => {
                            Err(BindingError::runtime("Deno execution was cancelled"))
                        }
                    }
                });
                let _ = respond_to.send(result);
            }
            ExecutionCommand::Shutdown => break,
        }
    }

    runtime.shutdown_background();
}

enum ExecutionBackend {
    Lightweight(Box<JsRuntime>),
    Package(Box<LibMainWorker>),
}

struct InvocationKeepalive {
    tracker: ExternalOpsTracker,
}

impl InvocationKeepalive {
    fn new(runtime: &JsRuntime) -> Self {
        let tracker = runtime.op_state().borrow().external_ops_tracker.clone();
        tracker.ref_op();
        Self { tracker }
    }
}

impl Drop for InvocationKeepalive {
    fn drop(&mut self) {
        self.tracker.unref_op();
    }
}

struct DenoExecutionContext {
    bound: BoundRuntime,
    backend: ExecutionBackend,
    main_module: ModuleSpecifier,
    run_function: Option<v8::Global<v8::Function>>,
}

impl DenoExecutionContext {
    async fn new(
        bound: BoundRuntime,
        worker_factory_roots: &LibWorkerFactoryRoots,
    ) -> ExecutionResult<Self> {
        let main_module = main_module_specifier(&bound)?;
        let needs_package_worker = bound.package_environment().is_some()
            || deno_snapshots::CLI_SNAPSHOT.is_some()
            || bound.script().needs_package_loader();
        let backend = if needs_package_worker {
            let package_environment = match bound.package_environment() {
                Some(environment) => environment.clone(),
                None => BoundPackageEnvironment::implicit_for_cwd(bound.cwd())?,
            };
            let context = package_environment.embed_context_rc(bound.worker_options())?;
            ExecutionBackend::Package(Box::new(
                package_worker::create_bound_package_worker(
                    context,
                    bound.cwd().to_path_buf(),
                    main_module.clone(),
                    package_worker::BoundPackageWorkerOptions {
                        argv: Vec::new(),
                        argv0: None,
                        js_runtime_options: bound.js_runtime_options().clone(),
                        runtime_worker_options: bound.worker_options().clone(),
                        main_source: Some(bound.script().execution_content()),
                        header_overrides: content_type_header_overrides(
                            main_module.clone(),
                            bound.script().media_type(),
                        ),
                    },
                    worker_factory_roots,
                )
                .await?,
            ))
        } else {
            ExecutionBackend::Lightweight(Box::new(create_js_runtime(&bound)?))
        };
        Ok(Self {
            bound,
            backend,
            main_module,
            run_function: None,
        })
    }

    fn js_runtime(&mut self) -> &mut JsRuntime {
        match &mut self.backend {
            ExecutionBackend::Lightweight(js_runtime) => js_runtime,
            ExecutionBackend::Package(worker) => worker.js_runtime(),
        }
    }

    async fn invoke(&mut self, arguments: RunnerArguments) -> ExecutionResult<PyJsValue> {
        self.ensure_loaded().await?;
        let run_function = self
            .run_function
            .clone()
            .ok_or_else(|| BindingError::missing_run_export(self.bound.description()))?;
        let run_signature = self.bound.run_signature().cloned();
        let args = {
            deno_core::scope!(scope, self.js_runtime());
            arguments.to_v8_globals(scope, run_signature.as_ref())?
        };
        let _keepalive = InvocationKeepalive::new(self.js_runtime());
        let call = self.js_runtime().call_with_args(&run_function, &args);
        let result = self
            .js_runtime()
            .with_event_loop_promise(call, PollEventLoopOptions::default())
            .await
            .map_err(|error| BindingError::javascript(error.to_string()))?;
        deno_core::scope!(scope, self.js_runtime());
        let result = v8::Local::new(scope, result);
        PyJsValue::from_v8(scope, result)
    }

    async fn ensure_loaded(&mut self) -> ExecutionResult<()> {
        if self.run_function.is_some() {
            return Ok(());
        }

        if self.bound.script().media_type() == deno_ast::MediaType::Tsx
            || self.bound.script().content().contains("@belgie/render")
        {
            self.install_safe_process_environment()?;
        }
        self.install_render_context()?;

        let module_id = match &mut self.backend {
            ExecutionBackend::Package(worker) => {
                let js_runtime = worker.js_runtime();
                js_runtime
                    .load_main_es_module(&self.main_module)
                    .await
                    .map_err(|error| BindingError::module_load(error.to_string()))?
            }
            ExecutionBackend::Lightweight(js_runtime) => js_runtime
                .load_main_es_module_from_code(
                    &self.main_module,
                    module_loader::maybe_transpile_source(
                        &self.main_module,
                        self.bound.script().execution_content(),
                    )
                    .map_err(|error| BindingError::module_load(error.to_string()))?,
                )
                .await
                .map_err(|error| BindingError::module_load(error.to_string()))?,
        };

        evaluate_loaded_module(self.js_runtime(), module_id).await?;

        let namespace = self
            .js_runtime()
            .get_module_namespace(module_id)
            .map_err(|error| BindingError::module_load(error.to_string()))?;
        let description = self.bound.description();
        let run_function = resolve_run_function(self.js_runtime(), namespace, &description)?;

        self.run_function = Some(run_function);
        Ok(())
    }

    fn install_render_context(&mut self) -> ExecutionResult<()> {
        let source = self.bound.script().content().to_string();
        let url = self.main_module.to_string();
        deno_core::scope!(scope, self.js_runtime());

        let context = v8::Object::new(scope);
        let version = v8::Integer::new(scope, 1);
        define_context_property(scope, context, "version", version.into())?;
        let source_value = v8::String::new(scope, &source)
            .ok_or_else(|| BindingError::runtime("Could not create render context source"))?;
        define_context_property(scope, context, "source", source_value.into())?;
        let url_value = v8::String::new(scope, &url)
            .ok_or_else(|| BindingError::runtime("Could not create render context URL"))?;
        define_context_property(scope, context, "url", url_value.into())?;
        if !context
            .set_integrity_level(scope, v8::IntegrityLevel::Frozen)
            .unwrap_or(false)
        {
            return Err(BindingError::runtime("Could not freeze render context"));
        }

        let symbol_name = v8::String::new(scope, RENDER_CONTEXT_SYMBOL)
            .ok_or_else(|| BindingError::runtime("Could not create render context symbol"))?;
        let symbol = v8::Symbol::for_key(scope, symbol_name);
        let global = scope.get_current_context().global(scope);
        let attributes = v8::PropertyAttribute::READ_ONLY
            | v8::PropertyAttribute::DONT_ENUM
            | v8::PropertyAttribute::DONT_DELETE;
        if !global
            .define_own_property(scope, symbol.into(), context.into(), attributes)
            .unwrap_or(false)
        {
            return Err(BindingError::runtime("Could not install render context"));
        }
        Ok(())
    }

    fn install_safe_process_environment(&mut self) -> ExecutionResult<()> {
        deno_core::scope!(scope, self.js_runtime());
        let global = scope.get_current_context().global(scope);
        let process_key = v8::String::new(scope, "process")
            .ok_or_else(|| BindingError::runtime("Could not create process key"))?;
        let process_value = global
            .get(scope, process_key.into())
            .ok_or_else(|| BindingError::runtime("Could not access process global"))?;
        let process = v8::Local::<v8::Object>::try_from(process_value)
            .map_err(|_| BindingError::runtime("Could not access process object"))?;

        let environment = v8::Object::new(scope);
        for (name, value) in SAFE_PROCESS_ENVIRONMENT {
            let value = v8::String::new(scope, value).ok_or_else(|| {
                BindingError::runtime("Could not create process environment value")
            })?;
            define_context_property(scope, environment, name, value.into())?;
        }
        if !environment
            .set_integrity_level(scope, v8::IntegrityLevel::Frozen)
            .unwrap_or(false)
        {
            return Err(BindingError::runtime(
                "Could not freeze process environment",
            ));
        }

        let environment_key = v8::String::new(scope, "env")
            .ok_or_else(|| BindingError::runtime("Could not create process environment key"))?;
        if !process
            .define_own_property(
                scope,
                environment_key.into(),
                environment.into(),
                v8::PropertyAttribute::NONE,
            )
            .unwrap_or(false)
        {
            return Err(BindingError::runtime(
                "Could not install safe process environment",
            ));
        }
        Ok(())
    }
}

fn define_context_property<'s, 'i>(
    scope: &mut v8::PinScope<'s, 'i>,
    object: v8::Local<'s, v8::Object>,
    name: &str,
    value: v8::Local<'s, v8::Value>,
) -> ExecutionResult<()> {
    let key = v8::String::new(scope, name)
        .ok_or_else(|| BindingError::runtime("Could not create render context key"))?;
    if !object
        .define_own_property(
            scope,
            key.into(),
            value,
            v8::PropertyAttribute::READ_ONLY | v8::PropertyAttribute::DONT_DELETE,
        )
        .unwrap_or(false)
    {
        return Err(BindingError::runtime(format!(
            "Could not define render context property {name}",
        )));
    }
    Ok(())
}

async fn evaluate_loaded_module(
    js_runtime: &mut JsRuntime,
    module_id: ModuleId,
) -> ExecutionResult<()> {
    let result = js_runtime.mod_evaluate(module_id);
    js_runtime
        .run_event_loop(Default::default())
        .await
        .map_err(map_core_error)?;
    result
        .await
        .map_err(|error| BindingError::javascript(error.to_string()))
}

fn map_core_error(error: CoreError) -> BindingError {
    BindingError::javascript(error.to_string())
}

fn main_module_specifier(bound: &BoundRuntime) -> ExecutionResult<ModuleSpecifier> {
    let path = bound
        .script()
        .filename()
        .map_or_else(|| inline_module_path(bound), PathBuf::from);
    ModuleSpecifier::from_file_path(&path).map_err(|_| {
        BindingError::module_load(format!("Could not convert {} to file URL", path.display()))
    })
}

fn inline_module_path(bound: &BoundRuntime) -> PathBuf {
    let filename = if bound.script().media_type() == deno_ast::MediaType::Tsx {
        "__deno_python_inline__.tsx"
    } else {
        "__deno_python_inline__.ts"
    };
    bound.cwd().join(filename)
}

fn create_js_runtime(bound: &BoundRuntime) -> ExecutionResult<JsRuntime> {
    Ok(JsRuntime::new(RuntimeOptions {
        module_loader: Some(Rc::new(module_loader::PythonModuleLoader)),
        create_params: bound
            .js_runtime_options()
            .to_create_params()
            .map_err(BindingError::runtime)?,
        ..Default::default()
    }))
}

#[cfg(test)]
pub(crate) fn with_test_js_runtime<F, R>(f: F) -> R
where
    F: FnOnce(&mut JsRuntime) -> R + Send + 'static,
    R: Send + 'static,
{
    spawn_v8_worker(move || {
        if deno_snapshots::CLI_SNAPSHOT.is_some() {
            create_and_run_current_thread(async move {
                let cwd = std::env::current_dir().expect("current dir should be available");
                let package_environment = BoundPackageEnvironment::implicit_for_cwd(&cwd)
                    .expect("implicit package environment should initialize");
                let worker_options = crate::options::RuntimeWorkerOptions::default();
                let context = package_environment
                    .embed_context_rc(&worker_options)
                    .expect("embed context should initialize");
                let main_module = ModuleSpecifier::from_file_path(cwd.join("__belgie_test__.ts"))
                    .expect("test module path should convert to file URL");
                let mut worker = package_worker::create_bound_package_worker(
                    context,
                    cwd,
                    main_module.clone(),
                    package_worker::BoundPackageWorkerOptions {
                        argv: Vec::new(),
                        argv0: None,
                        js_runtime_options: Default::default(),
                        runtime_worker_options: Default::default(),
                        main_source: Some("export {}".to_string()),
                        header_overrides: content_type_header_overrides(
                            main_module,
                            deno_ast::MediaType::TypeScript,
                        ),
                    },
                    &LibWorkerFactoryRoots::default(),
                )
                .await
                .expect("package worker should initialize for tests");
                f(worker.js_runtime())
            })
        } else {
            let mut runtime = JsRuntime::new(RuntimeOptions::default());
            f(&mut runtime)
        }
    })
    .join()
    .expect("v8 worker thread should not panic")
}

fn resolve_run_function(
    runtime: &mut deno_core::JsRuntime,
    namespace: v8::Global<v8::Object>,
    context: &str,
) -> ExecutionResult<v8::Global<v8::Function>> {
    deno_core::scope!(scope, runtime);
    let namespace = v8::Local::new(scope, namespace);
    let default_key = v8::String::new(scope, "default")
        .ok_or_else(|| BindingError::runtime("Could not create default export key"))?;
    let run_key = v8::String::new(scope, "run")
        .ok_or_else(|| BindingError::runtime("Could not create run export key"))?;
    let default_export = namespace.get(scope, default_key.into());
    if let Some(default_export) = default_export
        && default_export.is_function()
    {
        let function = v8::Local::<v8::Function>::try_from(default_export)
            .map_err(|_| BindingError::non_function_run_export(context.to_string()))?;
        return Ok(v8::Global::new(scope, function));
    }

    let run_export = namespace
        .get(scope, run_key.into())
        .ok_or_else(|| BindingError::missing_run_export(context.to_string()))?;
    if run_export.is_undefined() {
        return Err(BindingError::missing_run_export(context.to_string()));
    }
    if !run_export.is_function() {
        return Err(BindingError::non_function_run_export(context.to_string()));
    }
    let function = v8::Local::<v8::Function>::try_from(run_export)
        .map_err(|_| BindingError::non_function_run_export(context.to_string()))?;
    Ok(v8::Global::new(scope, function))
}
