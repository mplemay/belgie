use pyo3::prelude::*;

use crate::{binding::blocking, task::TaskProcess};

#[pyclass(name = "TaskProcess", module = "belgie._core")]
pub(crate) struct PyTaskProcess {
    inner: TaskProcess,
}

impl PyTaskProcess {
    pub(crate) fn new(process: TaskProcess) -> Self {
        Self { inner: process }
    }
}

#[pymethods]
impl PyTaskProcess {
    #[getter]
    fn origin(&self) -> String {
        self.inner.origin().unwrap_or_default().to_string()
    }

    #[getter]
    fn is_running(&self) -> bool {
        self.inner.is_running_blocking()
    }

    fn stop<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let process = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            blocking::run_on_blocking_thread(move || process.stop_blocking(), "Task stop failed")
                .await
        })
    }

    fn __repr__(&self) -> String {
        let is_running = self.inner.is_running_blocking();
        format!(
            "TaskProcess(origin={:?}, is_running={is_running})",
            self.inner.origin(),
        )
    }
}
