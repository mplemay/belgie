use std::{
    path::PathBuf,
    rc::Rc,
    sync::{Arc, Mutex, mpsc},
    thread,
};

use deno_core::{
    JsRuntime, ModuleId, ModuleSpecifier, PollEventLoopOptions, RuntimeOptions, error::CoreError,
    v8,
};
use deno_lib::worker::{LibMainWorker, LibWorkerFactoryRoots};
use tokio::sync::oneshot;

use crate::{
    embed::runtime::ts_content_type_header_overrides,
    runtime::{module_loader, package_worker, process_context},
    types::{error::BindingError, runner::RunnerArguments, value::PyJsValue},
    utils::cancel_guard::Cancel,
};

use super::{BoundRuntime, RuntimeSession};

type ExecutionResult<T> = Result<T, BindingError>;

#[derive(Clone, Debug)]
pub(crate) struct DenoExecutionHandle {
    inner: Arc<DenoExecutionHandleInner>,
}

#[derive(Debug)]
struct DenoExecutionHandleInner {
    sender: mpsc::Sender<ExecutionCommand>,
    isolate_handle: Arc<Mutex<Option<v8::IsolateHandle>>>,
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
    pub(crate) fn new(bound: BoundRuntime, session: Arc<RuntimeSession>) -> Self {
        let (sender, receiver) = mpsc::channel();
        let isolate_handle = Arc::new(Mutex::new(None));
        let worker_isolate_handle = isolate_handle.clone();
        let join_handle = thread::spawn(move || {
            run_worker_thread(bound, session, receiver, worker_isolate_handle)
        });
        Self {
            inner: Arc::new(DenoExecutionHandleInner {
                sender,
                isolate_handle,
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
    session: Arc<RuntimeSession>,
    receiver: mpsc::Receiver<ExecutionCommand>,
    isolate_handle: Arc<Mutex<Option<v8::IsolateHandle>>>,
) {
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            let init_error =
                BindingError::runtime(format!("Creating Deno execution runtime failed: {error}"));
            while let Ok(command) = receiver.recv() {
                match command {
                    ExecutionCommand::Invoke { respond_to, .. } => {
                        let _ = respond_to.send(Err(init_error.clone()));
                    }
                    ExecutionCommand::Shutdown => break,
                }
            }
            return;
        }
    };
    let mut context = {
        let _process_context = process_context::blocking_guard();
        match runtime.block_on(DenoExecutionContext::new(
            bound,
            session.cli_snapshot_eligible(),
            session.worker_factory_roots(),
        )) {
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
                let result = runtime.block_on(context.invoke(arguments));
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

struct DenoExecutionContext {
    bound: BoundRuntime,
    backend: ExecutionBackend,
    main_module: ModuleSpecifier,
    run_function: Option<v8::Global<v8::Function>>,
}

impl DenoExecutionContext {
    async fn new(
        bound: BoundRuntime,
        use_cli_snapshot: bool,
        worker_factory_roots: &LibWorkerFactoryRoots,
    ) -> ExecutionResult<Self> {
        let main_module = main_module_specifier(&bound)?;
        let backend = if let Some(package_environment) = bound.package_environment() {
            let context = package_environment.embed_context_rc(bound.worker_options())?;
            ExecutionBackend::Package(Box::new(
                package_worker::create_bound_package_worker(
                    context,
                    bound.cwd().to_path_buf(),
                    main_module.clone(),
                    package_worker::BoundPackageWorkerOptions {
                        argv: Vec::new(),
                        argv0: None,
                        use_cli_snapshot,
                        js_runtime_options: bound.js_runtime_options().clone(),
                        runtime_worker_options: bound.worker_options().clone(),
                        main_source: Some(bound.script().content().to_string()),
                        header_overrides: ts_content_type_header_overrides(main_module.clone()),
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
                        self.bound.script().content().to_string(),
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
        .path()
        .map_or_else(|| inline_module_path(bound), PathBuf::from);
    ModuleSpecifier::from_file_path(&path).map_err(|_| {
        BindingError::module_load(format!("Could not convert {} to file URL", path.display()))
    })
}

fn inline_module_path(bound: &BoundRuntime) -> PathBuf {
    bound.cwd().join("__deno_python_inline__.ts")
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
