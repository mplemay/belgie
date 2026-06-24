use std::sync::Arc;

use pyo3::{
    Borrowed, Bound, FromPyObject, PyAny, PyErr, PyResult, Python,
    exceptions::PyTypeError,
    prelude::*,
    types::{PyAnyMethods, PyDict, PyTuple},
};

use crate::{
    binding::{PyCommand, PyScript},
    command::CommandSource,
    runtime::{DenoExecutionHandle, RuntimeSession, executor},
    script::ScriptSource,
    types::runner::RunnerArguments,
    utils::{cancel_guard::CancelGuard, py_error},
};

#[pyclass(name = "SyncRuntime", module = "belgie._core")]
#[derive(Debug)]
pub struct PySyncRuntime {
    session: Arc<RuntimeSession>,
}

#[pyclass(name = "AsyncRuntime", module = "belgie._core")]
#[derive(Debug)]
pub struct PyAsyncRuntime {
    session: Arc<RuntimeSession>,
}

#[pyclass(name = "SyncRunner", module = "belgie._core")]
#[derive(Debug)]
pub struct PySyncRunner {
    handle: DenoExecutionHandle,
    description: String,
}

#[pyclass(name = "AsyncRunner", module = "belgie._core")]
#[derive(Debug)]
pub struct PyAsyncRunner {
    handle: DenoExecutionHandle,
    description: String,
}

#[pyclass(name = "SyncCommandRunner", module = "belgie._core")]
#[derive(Debug)]
pub struct PySyncCommandRunner {
    session: Arc<RuntimeSession>,
    command: CommandSource,
}

#[pyclass(name = "AsyncCommandRunner", module = "belgie._core")]
#[derive(Debug)]
pub struct PyAsyncCommandRunner {
    session: Arc<RuntimeSession>,
    command: CommandSource,
}

enum RuntimeTargetArg {
    Script {
        source: ScriptSource,
        description: String,
    },
    Command(CommandSource),
}

impl FromPyObject<'_, '_> for RuntimeTargetArg {
    type Error = PyErr;

    fn extract(obj: Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(script) = obj.extract::<PyRef<'_, PyScript>>() {
            let source = script.source();
            let description = source.description();
            return Ok(Self::Script {
                source,
                description,
            });
        }
        if let Ok(command) = obj.extract::<PyRef<'_, PyCommand>>() {
            return Ok(Self::Command(command.source()));
        }
        Err(PyTypeError::new_err(
            "Runtime target must be a Script or Command",
        ))
    }
}

#[pymethods]
impl PySyncRuntime {
    fn __call__(&self, py: Python<'_>, target: RuntimeTargetArg) -> PyResult<Py<PyAny>> {
        match target {
            RuntimeTargetArg::Script {
                source,
                description,
            } => {
                let handle = RuntimeSession::bind_script(&self.session, source)
                    .map_err(py_error::from_binding_error)?;
                Ok(Py::new(py, PySyncRunner::from_handle(handle, description))?.into_any())
            }
            RuntimeTargetArg::Command(command) => Ok(Py::new(
                py,
                PySyncCommandRunner::new(self.session.clone(), command),
            )?
            .into_any()),
        }
    }

    fn __repr__(&self) -> String {
        format!("SyncRuntime({})", self.session.description())
    }
}

#[pymethods]
impl PyAsyncRuntime {
    fn __call__(&self, py: Python<'_>, target: RuntimeTargetArg) -> PyResult<Py<PyAny>> {
        match target {
            RuntimeTargetArg::Script {
                source,
                description,
            } => {
                let handle = RuntimeSession::bind_script(&self.session, source)
                    .map_err(py_error::from_binding_error)?;
                Ok(Py::new(py, PyAsyncRunner::from_handle(handle, description))?.into_any())
            }
            RuntimeTargetArg::Command(command) => Ok(Py::new(
                py,
                PyAsyncCommandRunner::new(self.session.clone(), command),
            )?
            .into_any()),
        }
    }

    fn __repr__(&self) -> String {
        format!("AsyncRuntime({})", self.session.description())
    }
}

#[pymethods]
impl PySyncRunner {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__(
        &self,
        py: Python<'_>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        executor::execute_sync(py, &self.handle, RunnerArguments::from_py(args, kwargs)?)
    }

    fn __repr__(&self) -> String {
        format!("SyncRunner({})", self.description)
    }
}

#[pymethods]
impl PyAsyncRunner {
    #[pyo3(signature = (*args, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let handle = self.handle.clone();
        let arguments = RunnerArguments::from_py(args, kwargs)?;
        let awaitable = pyo3_async_runtimes::tokio::future_into_py(py, async move {
            executor::execute_async(handle, arguments).await
        })?;
        as_coroutine(py, awaitable)
    }

    fn __repr__(&self) -> String {
        format!("AsyncRunner({})", self.description)
    }
}

#[pymethods]
impl PySyncCommandRunner {
    #[pyo3(signature = (*args))]
    fn __call__(&self, py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<Py<PyAny>> {
        let argv = command_arguments(args)?;
        let handle =
            RuntimeSession::start_command(self.session.clone(), self.command.clone(), argv)
                .map_err(py_error::from_binding_error)?;
        py.detach(|| handle.wait_blocking())
            .map_err(py_error::from_binding_error)?;
        Ok(py.None())
    }

    fn __repr__(&self) -> String {
        format!("SyncCommandRunner({})", self.command.description())
    }
}

#[pymethods]
impl PyAsyncCommandRunner {
    #[pyo3(signature = (*args))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        args: &Bound<'py, PyTuple>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let argv = command_arguments(args)?;
        let handle =
            RuntimeSession::start_command(self.session.clone(), self.command.clone(), argv)
                .map_err(py_error::from_binding_error)?;
        let awaitable = pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = CancelGuard::new(handle);
            guard
                .get()
                .wait_async()
                .await
                .map_err(py_error::from_binding_error)?;
            guard.disarm();
            Ok(Python::attach(|py| py.None()))
        })?;
        as_coroutine(py, awaitable)
    }

    fn __repr__(&self) -> String {
        format!("AsyncCommandRunner({})", self.command.description())
    }
}

impl PySyncRuntime {
    pub(crate) fn new(session: Arc<RuntimeSession>) -> Self {
        Self { session }
    }
}

impl PyAsyncRuntime {
    pub(crate) fn new(session: Arc<RuntimeSession>) -> Self {
        Self { session }
    }
}

impl PySyncRunner {
    pub(crate) fn from_handle(handle: DenoExecutionHandle, description: String) -> Self {
        Self {
            handle,
            description,
        }
    }
}

impl PyAsyncRunner {
    pub(crate) fn from_handle(handle: DenoExecutionHandle, description: String) -> Self {
        Self {
            handle,
            description,
        }
    }
}

impl PySyncCommandRunner {
    fn new(session: Arc<RuntimeSession>, command: CommandSource) -> Self {
        Self { session, command }
    }
}

impl PyAsyncCommandRunner {
    fn new(session: Arc<RuntimeSession>, command: CommandSource) -> Self {
        Self { session, command }
    }
}

fn command_arguments(args: &Bound<'_, PyTuple>) -> PyResult<Vec<String>> {
    args.iter()
        .enumerate()
        .map(|(index, value)| {
            value.extract::<String>().map_err(|_| {
                pyo3::exceptions::PyTypeError::new_err(format!(
                    "Command argument {index} must be str"
                ))
            })
        })
        .collect()
}

fn as_coroutine<'py>(py: Python<'py>, awaitable: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    py.import("belgie._awaitable")?
        .getattr("as_coroutine")?
        .call1((awaitable,))
}
