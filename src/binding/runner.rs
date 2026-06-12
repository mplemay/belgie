use pyo3::{
    Bound, PyResult, Python,
    prelude::*,
    types::{PyDict, PyTuple},
};

use crate::{
    runtime::{DenoExecutionHandle, executor},
    types::runner::RunnerArguments,
};

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
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            executor::execute_async(handle, arguments).await
        })
    }

    fn __repr__(&self) -> String {
        format!("AsyncRunner({})", self.description)
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
