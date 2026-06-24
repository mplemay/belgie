use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
};

use pyo3::{
    Borrowed, Bound, FromPyObject, PyAny, PyErr, PyResult, Python,
    exceptions::{PyBaseException, PyTypeError, PyValueError},
    prelude::*,
    types::{PyTraceback, PyType},
};

use crate::{
    binding::{
        PyAsyncEnvironment, PyAsyncRuntime, PyEnvironment, PySyncEnvironment, PySyncRuntime,
    },
    environment::SharedEnvironment,
    options::{JsRuntimeOptions, RuntimeEnvironment, RuntimeOptions as InternalRuntimeOptions},
    runtime::{DenoRuntime, RuntimeSession},
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
    fn new(
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

#[derive(Debug)]
enum RuntimeContextState {
    Inactive,
    Entering,
    Active(Arc<RuntimeSession>),
}

#[pyclass(name = "Runtime", module = "belgie._core")]
#[derive(Debug)]
pub struct PyRuntime {
    inner: DenoRuntime,
    context_state: Arc<Mutex<RuntimeContextState>>,
    project: bool,
}

enum RuntimeEnvironmentArg {
    Environment(SharedEnvironment),
    SyncEnvironment(SharedEnvironment),
    AsyncEnvironment(SharedEnvironment),
}

impl RuntimeEnvironmentArg {
    fn into_shared(self) -> SharedEnvironment {
        match self {
            Self::Environment(environment)
            | Self::SyncEnvironment(environment)
            | Self::AsyncEnvironment(environment) => environment,
        }
    }
}

impl FromPyObject<'_, '_> for RuntimeEnvironmentArg {
    type Error = PyErr;

    fn extract(obj: Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(environment) = obj.extract::<PyRef<'_, PyEnvironment>>() {
            return Ok(Self::Environment(environment.environment()));
        }
        if let Ok(environment) = obj.extract::<PyRef<'_, PySyncEnvironment>>() {
            return Ok(Self::SyncEnvironment(environment.environment()));
        }
        if let Ok(environment) = obj.extract::<PyRef<'_, PyAsyncEnvironment>>() {
            return Ok(Self::AsyncEnvironment(environment.environment()));
        }
        Err(PyTypeError::new_err(
            "env must be Environment, SyncEnvironment, or AsyncEnvironment",
        ))
    }
}

#[pymethods]
impl PyRuntime {
    #[new]
    #[pyo3(signature = (*, env = None, options = None))]
    fn new(
        py: Python<'_>,
        env: Option<RuntimeEnvironmentArg>,
        options: Option<PyRef<'_, PyRuntimeOptions>>,
    ) -> PyResult<Self> {
        let environment = env
            .map(RuntimeEnvironmentArg::into_shared)
            .map(RuntimeEnvironment::Isolated);
        let cwd = environment.as_ref().map_or_else(
            || normalize_path::normalize_cwd(py, None),
            |environment| {
                Ok(environment
                    .isolated()
                    .expect("isolated runtime environment should contain Environment")
                    .workspace()
                    .to_path_buf())
            },
        )?;
        Ok(Self::from_parts(
            cwd,
            environment,
            options.as_deref(),
            false,
        ))
    }

    #[classmethod]
    #[pyo3(signature = (path, *, options = None))]
    fn from_folder(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        path: PathBuf,
        options: Option<PyRef<'_, PyRuntimeOptions>>,
    ) -> PyResult<Self> {
        let path = normalize_path::normalize_directory(py, path, "path")?;
        Ok(Self::from_parts(path, None, options.as_deref(), true))
    }

    fn __enter__(&self) -> PyResult<PySyncRuntime> {
        self.start_enter()?;
        let mut guard = RuntimeEnterGuard::new(&self.context_state);
        let session =
            RuntimeSession::activate(self.inner.clone()).map_err(py_error::from_binding_error)?;
        self.activate(session.clone());
        guard.disarm();
        Ok(PySyncRuntime::new(session))
    }

    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: Option<&Bound<'_, PyType>>,
        _exc: Option<&Bound<'_, PyBaseException>>,
        _traceback: Option<&Bound<'_, PyTraceback>>,
    ) -> PyResult<bool> {
        let session = self.take_active()?;
        py.detach(|| session.close_blocking())
            .map_err(py_error::from_binding_error)?;
        Ok(false)
    }

    fn __aenter__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.start_enter()?;
        let runtime = self.inner.clone();
        let context_state = self.context_state.clone();
        let mut enter_guard = RuntimeEnterGuard::new(&self.context_state);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let session =
                RuntimeSession::activate(runtime).map_err(py_error::from_binding_error)?;
            set_active(&context_state, session.clone());
            enter_guard.disarm();
            Ok(PyAsyncRuntime::new(session))
        })
    }

    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<&Bound<'_, PyType>>,
        _exc: Option<&Bound<'_, PyBaseException>>,
        _traceback: Option<&Bound<'_, PyTraceback>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let session = self.take_active()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            tokio::task::spawn_blocking(move || session.close_blocking())
                .await
                .map_err(|error| {
                    pyo3::exceptions::PyRuntimeError::new_err(format!(
                        "Belgie runtime close task failed: {error}"
                    ))
                })?
                .map_err(py_error::from_binding_error)?;
            Ok(false)
        })
    }

    fn __repr__(&self) -> String {
        if self.project {
            format!("Runtime.from_folder({})", self.inner.cwd().display())
        } else {
            match self.inner.environment() {
                Some(environment) => {
                    let env = environment
                        .isolated()
                        .expect("isolated runtime environment should contain Environment");
                    match env.persist_path() {
                        Some(path) => format!(
                            "Runtime(env=Environment(path={}, dependencies={}))",
                            path.display(),
                            env.dependency_count(),
                        ),
                        None => format!(
                            "Runtime(env=Environment(path=None, workspace={}, dependencies={}))",
                            self.inner.cwd().display(),
                            env.dependency_count(),
                        ),
                    }
                }
                None => "Runtime(env=None)".to_string(),
            }
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
    fn from_parts(
        cwd: std::path::PathBuf,
        environment: Option<RuntimeEnvironment>,
        options: Option<&PyRuntimeOptions>,
        project: bool,
    ) -> Self {
        let js_runtime_options = options
            .map(PyRuntimeOptions::js_runtime_options)
            .unwrap_or_default();
        Self {
            inner: DenoRuntime::new(InternalRuntimeOptions::new_with_js_runtime_options(
                cwd,
                js_runtime_options,
                environment,
            )),
            context_state: Arc::new(Mutex::new(RuntimeContextState::Inactive)),
            project,
        }
    }

    fn start_enter(&self) -> PyResult<()> {
        let mut state = self
            .context_state
            .lock()
            .expect("runtime context state lock should not be poisoned");
        match &*state {
            RuntimeContextState::Inactive => {
                *state = RuntimeContextState::Entering;
                Ok(())
            }
            RuntimeContextState::Entering | RuntimeContextState::Active(_) => Err(
                pyo3::exceptions::PyRuntimeError::new_err("Runtime context is already active"),
            ),
        }
    }

    fn activate(&self, session: Arc<RuntimeSession>) {
        set_active(&self.context_state, session);
    }

    fn take_active(&self) -> PyResult<Arc<RuntimeSession>> {
        let mut state = self
            .context_state
            .lock()
            .expect("runtime context state lock should not be poisoned");
        match std::mem::replace(&mut *state, RuntimeContextState::Inactive) {
            RuntimeContextState::Active(session) => Ok(session),
            RuntimeContextState::Entering => {
                *state = RuntimeContextState::Entering;
                Err(pyo3::exceptions::PyRuntimeError::new_err(
                    "Runtime context is still entering",
                ))
            }
            RuntimeContextState::Inactive => Err(pyo3::exceptions::PyRuntimeError::new_err(
                "Runtime context is not active",
            )),
        }
    }
}

fn set_active(context_state: &Arc<Mutex<RuntimeContextState>>, session: Arc<RuntimeSession>) {
    *context_state
        .lock()
        .expect("runtime context state lock should not be poisoned") =
        RuntimeContextState::Active(session);
}

struct RuntimeEnterGuard {
    context_state: Arc<Mutex<RuntimeContextState>>,
    armed: bool,
}

impl RuntimeEnterGuard {
    fn new(context_state: &Arc<Mutex<RuntimeContextState>>) -> Self {
        Self {
            context_state: Arc::clone(context_state),
            armed: true,
        }
    }

    fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for RuntimeEnterGuard {
    fn drop(&mut self) {
        if self.armed {
            let session = {
                let mut state = self
                    .context_state
                    .lock()
                    .expect("runtime context state lock should not be poisoned");
                match std::mem::replace(&mut *state, RuntimeContextState::Inactive) {
                    RuntimeContextState::Active(session) => Some(session),
                    RuntimeContextState::Entering | RuntimeContextState::Inactive => None,
                }
            };
            if let Some(session) = session {
                let _ = session.close_blocking();
            }
        }
    }
}
