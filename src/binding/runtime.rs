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
        normalize,
    },
    environment::SharedEnvironment,
    exceptions::BelgieRuntimeError,
    options::{
        JsRuntimeOptions, RuntimeEnvironment, RuntimeOptions as InternalRuntimeOptions,
        RuntimePermissionOptions, RuntimeWorkerOptions,
    },
    runtime::{DenoRuntime, RuntimeSession},
    utils::{normalize_path, py_error},
};

#[pyclass(
    name = "RuntimePermissions",
    module = "belgie._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyRuntimePermissions {
    inner: RuntimePermissionOptions,
    mode: String,
}

#[pyclass(name = "RuntimeOptions", module = "belgie._core")]
#[derive(Debug)]
pub struct PyRuntimeOptions {
    js_runtime: JsRuntimeOptions,
    worker: RuntimeWorkerOptions,
    permissions_repr: String,
    log_level_repr: Option<String>,
}

#[pymethods]
impl PyRuntimePermissions {
    #[new]
    #[pyo3(signature = (*, allow_env = None, deny_env = None, ignore_env = None, allow_net = None, deny_net = None, allow_ffi = None, deny_ffi = None, allow_read = None, deny_read = None, ignore_read = None, allow_run = None, deny_run = None, allow_sys = None, deny_sys = None, allow_write = None, deny_write = None, allow_import = None, deny_import = None, prompt = false))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        allow_env: Option<Vec<String>>,
        deny_env: Option<Vec<String>>,
        ignore_env: Option<Vec<String>>,
        allow_net: Option<Vec<String>>,
        deny_net: Option<Vec<String>>,
        allow_ffi: Option<Vec<String>>,
        deny_ffi: Option<Vec<String>>,
        allow_read: Option<Vec<String>>,
        deny_read: Option<Vec<String>>,
        ignore_read: Option<Vec<String>>,
        allow_run: Option<Vec<String>>,
        deny_run: Option<Vec<String>>,
        allow_sys: Option<Vec<String>>,
        deny_sys: Option<Vec<String>>,
        allow_write: Option<Vec<String>>,
        deny_write: Option<Vec<String>>,
        allow_import: Option<Vec<String>>,
        deny_import: Option<Vec<String>>,
        prompt: bool,
    ) -> Self {
        Self {
            inner: RuntimePermissionOptions::configured(
                deno_runtime::deno_permissions::PermissionsOptions {
                    allow_env,
                    deny_env,
                    ignore_env,
                    allow_net,
                    deny_net,
                    allow_ffi,
                    deny_ffi,
                    allow_read,
                    deny_read,
                    ignore_read,
                    allow_run,
                    deny_run,
                    allow_sys,
                    deny_sys,
                    allow_write,
                    deny_write,
                    allow_import,
                    deny_import,
                    prompt,
                },
            ),
            mode: "configured".to_string(),
        }
    }

    #[classmethod]
    fn all(_cls: &Bound<'_, PyType>) -> Self {
        Self {
            inner: RuntimePermissionOptions::AllowAll,
            mode: "all".to_string(),
        }
    }

    #[classmethod]
    #[pyo3(signature = (*, prompt = false))]
    fn none(_cls: &Bound<'_, PyType>, prompt: bool) -> Self {
        Self {
            inner: RuntimePermissionOptions::none(prompt),
            mode: if prompt {
                "none(prompt=True)".to_string()
            } else {
                "none(prompt=False)".to_string()
            },
        }
    }

    fn __repr__(&self) -> String {
        format!("RuntimePermissions({})", self.mode)
    }
}

#[pymethods]
impl PyRuntimeOptions {
    #[new]
    #[pyo3(signature = (*, max_old_generation_size_mb = None, max_young_generation_size_mb = None, code_range_size_mb = None, permissions = None, seed = None, location = None, log_level = None, enable_testing_features = false, enable_raw_imports = false, disable_offscreen_canvas = false, trace_ops = None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        max_old_generation_size_mb: Option<i64>,
        max_young_generation_size_mb: Option<i64>,
        code_range_size_mb: Option<i64>,
        permissions: Option<PyRef<'_, PyRuntimePermissions>>,
        seed: Option<i64>,
        location: Option<&str>,
        log_level: Option<&str>,
        enable_testing_features: bool,
        enable_raw_imports: bool,
        disable_offscreen_canvas: bool,
        trace_ops: Option<Vec<String>>,
    ) -> PyResult<Self> {
        let log_level_value = normalize_log_level(log_level)?;
        Ok(Self {
            js_runtime: JsRuntimeOptions::new(
                normalize_memory_size("max_old_generation_size_mb", max_old_generation_size_mb)?,
                normalize_memory_size(
                    "max_young_generation_size_mb",
                    max_young_generation_size_mb,
                )?,
                normalize_memory_size("code_range_size_mb", code_range_size_mb)?,
            ),
            worker: RuntimeWorkerOptions::new(
                permissions
                    .as_deref()
                    .map(PyRuntimePermissions::runtime_permissions)
                    .unwrap_or_default(),
                normalize_seed(seed)?,
                normalize_location(location)?,
                log_level_value.0,
                enable_testing_features,
                enable_raw_imports,
                disable_offscreen_canvas,
                trace_ops,
            ),
            permissions_repr: permissions
                .as_deref()
                .map_or_else(|| "None".to_string(), repr_permission_mode),
            log_level_repr: log_level_value.1,
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "RuntimeOptions(max_old_generation_size_mb={:?}, max_young_generation_size_mb={:?}, code_range_size_mb={:?}, permissions={}, seed={:?}, location={:?}, log_level={:?}, disable_offscreen_canvas={:?})",
            self.js_runtime.max_old_generation_size_mb(),
            self.js_runtime.max_young_generation_size_mb(),
            self.js_runtime.code_range_size_mb(),
            self.permissions_repr,
            self.worker.seed(),
            self.worker.location().map(|url| url.to_string()),
            self.log_level_repr,
            self.worker.disable_offscreen_canvas(),
        )
    }
}

impl PyRuntimeOptions {
    pub(crate) fn js_runtime_options(&self) -> JsRuntimeOptions {
        self.js_runtime.clone()
    }

    pub(crate) fn worker_options(&self) -> RuntimeWorkerOptions {
        self.worker.clone()
    }
}

impl PyRuntimePermissions {
    pub(crate) fn runtime_permissions(&self) -> RuntimePermissionOptions {
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
        Self::from_parts(cwd, environment, options.as_deref(), false)
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
        Self::from_parts(path, None, options.as_deref(), true)
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

fn normalize_seed(value: Option<i64>) -> PyResult<Option<u64>> {
    normalize::normalize_non_negative_u64("seed", value)
}

fn normalize_location(value: Option<&str>) -> PyResult<Option<url::Url>> {
    value
        .map(|value| {
            url::Url::parse(value).map_err(|error| {
                PyValueError::new_err(format!("location must be a valid URL: {error}"))
            })
        })
        .transpose()
}

fn normalize_log_level(
    value: Option<&str>,
) -> PyResult<(Option<deno_runtime::WorkerLogLevel>, Option<String>)> {
    match value {
        None => Ok((None, None)),
        Some("error") => Ok((
            Some(deno_runtime::WorkerLogLevel::Error),
            Some("error".to_string()),
        )),
        Some("warn") => Ok((
            Some(deno_runtime::WorkerLogLevel::Warn),
            Some("warn".to_string()),
        )),
        Some("info") => Ok((
            Some(deno_runtime::WorkerLogLevel::Info),
            Some("info".to_string()),
        )),
        Some("debug") => Ok((
            Some(deno_runtime::WorkerLogLevel::Debug),
            Some("debug".to_string()),
        )),
        Some(value) => Err(PyValueError::new_err(format!(
            "log_level must be one of: error, warn, info, or debug; got {value:?}"
        ))),
    }
}

fn repr_permission_mode(permissions: &PyRuntimePermissions) -> String {
    format!("RuntimePermissions({})", permissions.mode)
}

impl PyRuntime {
    fn from_parts(
        cwd: std::path::PathBuf,
        environment: Option<RuntimeEnvironment>,
        options: Option<&PyRuntimeOptions>,
        project: bool,
    ) -> PyResult<Self> {
        let js_runtime_options = options
            .map(PyRuntimeOptions::js_runtime_options)
            .unwrap_or_default();
        let worker_options = options
            .map(PyRuntimeOptions::worker_options)
            .unwrap_or_default();
        if environment.is_none() && worker_options.requires_package_worker() {
            return Err(BelgieRuntimeError::new_err(
                "Deno worker RuntimeOptions require Runtime(env=Environment(...)); Runtime() and Runtime.from_folder() only support V8 memory options",
            ));
        }
        Ok(Self {
            inner: DenoRuntime::new(InternalRuntimeOptions::new_with_options(
                cwd,
                js_runtime_options,
                worker_options,
                environment,
            )),
            context_state: Arc::new(Mutex::new(RuntimeContextState::Inactive)),
            project,
        })
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
