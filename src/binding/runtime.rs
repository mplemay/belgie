use pyo3::{Bound, PyAny, PyResult, Python, exceptions::PyValueError, prelude::*};

use crate::{
    binding::{PyAsyncRunner, PyScript, PySyncRunner},
    options::{JsRuntimeOptions, RuntimeOptions as InternalRuntimeOptions},
    runtime::{BoundRuntime, DenoExecutionHandle, DenoRuntime},
    utils::{normalize_path, py_error},
};

#[pyclass(name = "RuntimeOptions", module = "belgie._core")]
#[derive(Debug)]
pub struct PyRuntimeOptions {
    inner: JsRuntimeOptions,
}

#[pymethods]
impl PyRuntimeOptions {
    #[new]
    #[pyo3(signature = (*, max_old_generation_size_mb = None, max_young_generation_size_mb = None, code_range_size_mb = None))]
    pub fn new(
        max_old_generation_size_mb: Option<i64>,
        max_young_generation_size_mb: Option<i64>,
        code_range_size_mb: Option<i64>,
    ) -> PyResult<Self> {
        Ok(Self {
            inner: JsRuntimeOptions::new(
                normalize_memory_size("max_old_generation_size_mb", max_old_generation_size_mb)?,
                normalize_memory_size(
                    "max_young_generation_size_mb",
                    max_young_generation_size_mb,
                )?,
                normalize_memory_size("code_range_size_mb", code_range_size_mb)?,
            ),
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "RuntimeOptions(max_old_generation_size_mb={:?}, max_young_generation_size_mb={:?}, code_range_size_mb={:?})",
            self.inner.max_old_generation_size_mb(),
            self.inner.max_young_generation_size_mb(),
            self.inner.code_range_size_mb(),
        )
    }
}

impl PyRuntimeOptions {
    pub(crate) fn js_runtime_options(&self) -> JsRuntimeOptions {
        self.inner.clone()
    }
}

#[pyclass(name = "Runtime", module = "belgie._core")]
#[derive(Debug)]
pub struct PyRuntime {
    inner: DenoRuntime,
    bound: Option<BoundRuntime>,
    active_handle: Option<DenoExecutionHandle>,
}

#[pymethods]
impl PyRuntime {
    #[new]
    #[pyo3(signature = (cwd = None, *, options = None))]
    pub fn new(
        py: Python<'_>,
        cwd: Option<&Bound<'_, PyAny>>,
        options: Option<PyRef<'_, PyRuntimeOptions>>,
    ) -> PyResult<Self> {
        let cwd = normalize_path::normalize_cwd(py, cwd)?;
        let js_runtime_options = options
            .as_deref()
            .map(PyRuntimeOptions::js_runtime_options)
            .unwrap_or_default();
        Ok(Self {
            inner: DenoRuntime::new(InternalRuntimeOptions::new_with_js_runtime_options(
                cwd,
                js_runtime_options,
            )),
            bound: None,
            active_handle: None,
        })
    }

    fn __call__(&self, script: PyRef<'_, PyScript>) -> Self {
        let bound = self.inner.bind(script.source());
        Self {
            inner: self.inner.clone(),
            bound: Some(bound),
            active_handle: None,
        }
    }

    fn __enter__(&mut self) -> PyResult<PySyncRunner> {
        self.ensure_not_active()?;
        let bound = self.bound_runtime()?;
        let description = bound.description();
        let handle = DenoExecutionHandle::new(bound);
        self.active_handle = Some(handle.clone());
        Ok(PySyncRunner::from_handle(handle, description))
    }

    fn __exit__(
        &mut self,
        py: Python<'_>,
        _exc_type: Option<&Bound<'_, PyAny>>,
        _exc: Option<&Bound<'_, PyAny>>,
        _traceback: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<bool> {
        self.close_active_sync(py)?;
        Ok(false)
    }

    fn __aenter__<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.ensure_not_active()?;
        let bound = self.bound_runtime()?;
        let description = bound.description();
        let handle = DenoExecutionHandle::new(bound);
        self.active_handle = Some(handle.clone());
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            Ok(PyAsyncRunner::from_handle(handle, description))
        })
    }

    fn __aexit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: Option<&Bound<'_, PyAny>>,
        _exc: Option<&Bound<'_, PyAny>>,
        _traceback: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let handle = self.active_handle.take();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            if let Some(handle) = handle {
                handle
                    .close_async()
                    .await
                    .map_err(py_error::from_binding_error)?;
            }
            Ok(false)
        })
    }

    fn __repr__(&self) -> String {
        match &self.bound {
            Some(bound) => format!("Runtime({})", bound.description()),
            None => format!("Runtime(cwd={})", self.inner.cwd().display()),
        }
    }
}

fn normalize_memory_size(field_name: &str, value: Option<i64>) -> PyResult<Option<u64>> {
    match value {
        Some(value) if value <= 0 => Err(PyValueError::new_err(format!(
            "{field_name} must be a positive integer"
        ))),
        Some(value) => Ok(Some(value as u64)),
        None => Ok(None),
    }
}

impl PyRuntime {
    fn bound_runtime(&self) -> PyResult<BoundRuntime> {
        self.bound.clone().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err(
                "Runtime must be bound to a Script before entering",
            )
        })
    }

    fn ensure_not_active(&self) -> PyResult<()> {
        if self
            .active_handle
            .as_ref()
            .is_some_and(|handle| !handle.is_closed())
        {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "Runtime context is already active",
            ));
        }
        Ok(())
    }

    fn close_active_sync(&mut self, py: Python<'_>) -> PyResult<()> {
        if let Some(handle) = self.active_handle.take() {
            py.detach(|| handle.close_blocking())
                .map_err(py_error::from_binding_error)?;
        }
        Ok(())
    }
}
