use std::{
    path::PathBuf,
    rc::Rc,
    sync::{Arc, Mutex, mpsc},
    thread,
};

use deno_core::{
    JsRuntime, ModuleSpecifier, PollEventLoopOptions, RuntimeOptions, error::CoreError, v8,
};
use tokio::sync::oneshot;

use crate::{
    embed::prepare_package_runtime,
    packages::PackageEnvironment,
    runtime::{BoundRuntime, module_loader},
    types::{error::BindingError, runner::RunnerArguments, value::PyJsValue},
};

type ExecutionResult<T> = Result<T, BindingError>;

#[derive(Clone, Debug)]
pub(crate) struct DenoExecutionHandle {
    inner: Arc<DenoExecutionHandleInner>,
}

#[derive(Debug)]
struct DenoExecutionHandleInner {
    sender: mpsc::Sender<ExecutionCommand>,
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
    pub(crate) fn new(bound: BoundRuntime) -> Self {
        let (sender, receiver) = mpsc::channel();
        let join_handle = thread::spawn(move || run_worker_thread(bound, receiver));
        Self {
            inner: Arc::new(DenoExecutionHandleInner {
                sender,
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

        let _ = self.inner.sender.send(ExecutionCommand::Shutdown);
        join_handle
            .join()
            .map_err(|_| BindingError::runtime("Deno execution worker panicked"))?;
        Ok(())
    }

    pub(crate) async fn close_async(&self) -> ExecutionResult<()> {
        let handle = self.clone();
        tokio::task::spawn_blocking(move || handle.close_blocking())
            .await
            .map_err(|error| {
                BindingError::runtime(format!("Deno execution worker close task failed: {error}"))
            })?
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

impl Drop for DenoExecutionHandleInner {
    fn drop(&mut self) {
        let _ = self.sender.send(ExecutionCommand::Shutdown);
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

fn run_worker_thread(bound: BoundRuntime, receiver: mpsc::Receiver<ExecutionCommand>) {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("failed to create Deno execution runtime");
    let mut context = match DenoExecutionContext::new(bound, &runtime) {
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
    };

    while let Ok(command) = receiver.recv() {
        match command {
            ExecutionCommand::Invoke {
                arguments,
                respond_to,
            } => {
                let result = runtime.block_on(context.invoke(arguments));
                let _ = respond_to.send(result);
            }
            ExecutionCommand::Shutdown => break,
        }
    }

    runtime.shutdown_background();
}

struct DenoExecutionContext {
    bound: BoundRuntime,
    js_runtime: JsRuntime,
    main_module: ModuleSpecifier,
    run_function: Option<v8::Global<v8::Function>>,
    uses_package_loader: bool,
}

impl DenoExecutionContext {
    fn new(bound: BoundRuntime, tokio_runtime: &tokio::runtime::Runtime) -> ExecutionResult<Self> {
        let main_module = main_module_specifier(&bound)?;
        let package_environment = PackageEnvironment::discover(bound.cwd().to_path_buf(), true)
            .map_err(|error| BindingError::runtime(error.to_string()))?;
        let uses_package_loader = package_environment.is_some();
        let js_runtime = if let Some(package_environment) = package_environment {
            tokio_runtime.block_on(create_js_runtime_with_packages(
                &bound,
                package_environment,
                main_module.clone(),
            ))?
        } else {
            create_js_runtime(&bound)?
        };
        Ok(Self {
            bound,
            js_runtime,
            main_module,
            run_function: None,
            uses_package_loader,
        })
    }

    async fn invoke(&mut self, arguments: RunnerArguments) -> ExecutionResult<PyJsValue> {
        self.ensure_loaded().await?;
        let run_function = self
            .run_function
            .as_ref()
            .ok_or_else(|| BindingError::missing_run_export(self.bound.description()))?;
        let args = {
            deno_core::scope!(scope, &mut self.js_runtime);
            arguments.to_v8_globals(scope)?
        };
        let call = self.js_runtime.call_with_args(run_function, &args);
        let result = self
            .js_runtime
            .with_event_loop_promise(call, PollEventLoopOptions::default())
            .await
            .map_err(|error| BindingError::javascript(error.to_string()))?;
        deno_core::scope!(scope, &mut self.js_runtime);
        let result = v8::Local::new(scope, result);
        PyJsValue::from_v8(scope, result)
    }

    async fn ensure_loaded(&mut self) -> ExecutionResult<()> {
        if self.run_function.is_some() {
            return Ok(());
        }

        let module_id = if self.uses_package_loader {
            self.js_runtime
                .load_main_es_module(&self.main_module)
                .await
                .map_err(|error| BindingError::module_load(error.to_string()))?
        } else {
            self.js_runtime
                .load_main_es_module_from_code(
                    &self.main_module,
                    module_loader::maybe_transpile_source(
                        &self.main_module,
                        self.bound.script().content().to_string(),
                    )
                    .map_err(|error| BindingError::module_load(error.to_string()))?,
                )
                .await
                .map_err(|error| BindingError::module_load(error.to_string()))?
        };

        let result = self.js_runtime.mod_evaluate(module_id);
        self.js_runtime
            .run_event_loop(Default::default())
            .await
            .map_err(map_core_error)?;
        result
            .await
            .map_err(|error| BindingError::javascript(error.to_string()))?;

        let namespace = self
            .js_runtime
            .get_module_namespace(module_id)
            .map_err(|error| BindingError::module_load(error.to_string()))?;
        let description = self.bound.description();
        let run_function = resolve_run_function(&mut self.js_runtime, namespace, &description)?;

        self.run_function = Some(run_function);
        Ok(())
    }
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

async fn create_js_runtime_with_packages(
    bound: &BoundRuntime,
    package_environment: PackageEnvironment,
    main_module: ModuleSpecifier,
) -> ExecutionResult<JsRuntime> {
    let context = package_environment
        .embed_context()
        .map_err(|error| BindingError::runtime(error.to_string()))?;
    let state = Rc::new(
        prepare_package_runtime(context, main_module, bound.script().content().to_string())
            .await
            .map_err(|error| BindingError::runtime(error.to_string()))?,
    );
    Ok(JsRuntime::new(RuntimeOptions {
        module_loader: Some(Rc::new(module_loader::PackageAwareModuleLoader::new(
            state,
            bound.cwd().to_path_buf(),
        ))),
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
    if !run_export.is_function() {
        return Err(BindingError::non_function_run_export(context.to_string()));
    }
    let function = v8::Local::<v8::Function>::try_from(run_export)
        .map_err(|_| BindingError::non_function_run_export(context.to_string()))?;
    Ok(v8::Global::new(scope, function))
}
