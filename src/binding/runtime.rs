use std::sync::{Arc, Mutex};

use pyo3::{Bound, PyAny, PyResult, Python, exceptions::PyValueError, prelude::*, types::PyType};

use crate::{
    binding::{
        PyAsyncRunner, PyEnvironment, PyScript, PySyncRunner, blocking,
        coerce::{self, GroupsDefault},
    },
    options::{JsRuntimeOptions, RuntimeEnvironment, RuntimeOptions as InternalRuntimeOptions},
    packages::ProjectPackageEnvironment,
    runtime::{BoundPackageEnvironment, BoundRuntime, DenoExecutionHandle, DenoRuntime},
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

#[derive(Debug)]
enum RuntimeContextState {
    Inactive,
    Entering,
    Active(DenoExecutionHandle),
}

#[pyclass(name = "Runtime", module = "belgie._core")]
#[derive(Debug)]
pub struct PyRuntime {
    inner: DenoRuntime,
    bound: Option<BoundRuntime>,
    context_state: Arc<Mutex<RuntimeContextState>>,
    project: bool,
}

#[pymethods]
impl PyRuntime {
    #[new]
    #[pyo3(signature = (*, env = None, options = None))]
    pub fn new(
        py: Python<'_>,
        env: Option<PyRef<'_, PyEnvironment>>,
        options: Option<PyRef<'_, PyRuntimeOptions>>,
    ) -> PyResult<Self> {
        let environment = env
            .as_deref()
            .map(PyEnvironment::environment)
            .map(RuntimeEnvironment::Isolated);
        let cwd = environment.as_ref().map_or_else(
            || normalize_path::normalize_cwd(py, None),
            |environment| {
                Ok(environment
                    .isolated()
                    .expect("isolated runtime environment should contain Environment")
                    .cwd()
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
    #[pyo3(signature = (path, *, groups = None, install = false, options = None))]
    fn from_folder(
        _cls: &Bound<'_, PyType>,
        path: &Bound<'_, PyAny>,
        groups: Option<&Bound<'_, PyAny>>,
        install: bool,
        options: Option<PyRef<'_, PyRuntimeOptions>>,
    ) -> PyResult<Self> {
        let py = path.py();
        let path = normalize_path::path_from_py(path, "path")?;
        let path = normalize_path::normalize_directory(py, path, "path")?;
        let groups = coerce::normalize_groups(groups, GroupsDefault::All)?;
        let environment = py
            .detach(|| {
                crate::utils::tokio::run_outside_runtime(|| {
                    ProjectPackageEnvironment::from_folder(path.clone(), groups.clone(), install)
                })
            })
            .map_err(blocking::any_error_to_py)?
            .map(RuntimeEnvironment::Project);
        Ok(Self::from_parts(
            path,
            environment,
            options.as_deref(),
            true,
        ))
    }

    fn __call__(&self, script: PyRef<'_, PyScript>) -> Self {
        let bound = self.inner.bind(script.source());
        Self {
            inner: self.inner.clone(),
            bound: Some(bound),
            context_state: Arc::new(Mutex::new(RuntimeContextState::Inactive)),
            project: self.project,
        }
    }

    fn __enter__(&self, py: Python<'_>) -> PyResult<PySyncRunner> {
        let bound = self.bound_runtime()?;
        self.start_enter()?;
        let mut guard = RuntimeEnterGuard::new(&self.context_state);
        let prepared = py
            .detach(|| prepare_bound_runtime(bound))
            .map_err(blocking::any_error_to_py)?;
        let (handle, description) = activate_prepared_runtime(prepared, &self.context_state);
        guard.disarm();
        Ok(PySyncRunner::from_handle(handle, description))
    }

    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: Option<&Bound<'_, PyAny>>,
        _exc: Option<&Bound<'_, PyAny>>,
        _traceback: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<bool> {
        let handle = self.take_active()?;
        let close_result = py
            .detach(|| handle.close_blocking())
            .map_err(py_error::from_binding_error);
        close_result?;
        Ok(false)
    }

    fn __aenter__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bound = self.bound_runtime()?;
        self.start_enter()?;
        let context_state = self.context_state.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = RuntimeEnterGuard::new(&context_state);
            let prepared = blocking::run_on_blocking_thread(
                move || prepare_bound_runtime(bound),
                "Belgie runtime environment activation failed",
            )
            .await?;
            let (handle, description) = activate_prepared_runtime(prepared, &context_state);
            guard.disarm();
            Ok(PyAsyncRunner::from_handle(handle, description))
        })
    }

    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<&Bound<'_, PyAny>>,
        _exc: Option<&Bound<'_, PyAny>>,
        _traceback: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let handle = self.take_active()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            handle
                .close_async()
                .await
                .map_err(py_error::from_binding_error)?;
            Ok(false)
        })
    }

    fn __repr__(&self) -> String {
        match &self.bound {
            Some(bound) => format!("Runtime({})", bound.description()),
            None if self.project => format!("Runtime.from_folder({})", self.inner.cwd().display()),
            None => match self.inner.environment() {
                Some(_) => format!(
                    "Runtime(env=Environment(cwd={}))",
                    self.inner.cwd().display()
                ),
                None => "Runtime(env=None)".to_string(),
            },
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
            bound: None,
            context_state: Arc::new(Mutex::new(RuntimeContextState::Inactive)),
            project,
        }
    }

    fn bound_runtime(&self) -> PyResult<BoundRuntime> {
        self.bound.clone().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err(
                "Runtime must be bound to a Script before entering",
            )
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

    fn take_active(&self) -> PyResult<DenoExecutionHandle> {
        let mut state = self
            .context_state
            .lock()
            .expect("runtime context state lock should not be poisoned");
        match std::mem::replace(&mut *state, RuntimeContextState::Inactive) {
            RuntimeContextState::Active(handle) => Ok(handle),
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

fn activate_prepared_runtime(
    prepared: BoundRuntime,
    context_state: &Arc<Mutex<RuntimeContextState>>,
) -> (DenoExecutionHandle, String) {
    let description = prepared.description();
    let handle = DenoExecutionHandle::new(prepared);
    *context_state
        .lock()
        .expect("runtime context state lock should not be poisoned") =
        RuntimeContextState::Active(handle.clone());
    (handle, description)
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
            abort_runtime_enter(&self.context_state);
        }
    }
}

fn abort_runtime_enter(context_state: &Arc<Mutex<RuntimeContextState>>) {
    let handle = {
        let mut state = context_state
            .lock()
            .expect("runtime context state lock should not be poisoned");
        match std::mem::replace(&mut *state, RuntimeContextState::Inactive) {
            RuntimeContextState::Active(handle) => Some(handle),
            RuntimeContextState::Entering | RuntimeContextState::Inactive => None,
        }
    };
    if let Some(handle) = handle {
        let _ = handle.close_blocking();
    }
}

fn prepare_bound_runtime(bound: BoundRuntime) -> Result<BoundRuntime, deno_core::error::AnyError> {
    let environment = match bound.runtime_environment() {
        Some(environment) => {
            if let Some(isolated) = environment.isolated() {
                let active = isolated.acquire_active()?;
                active
                    .uses_package_loader()
                    .then_some(BoundPackageEnvironment::Isolated(active))
            } else {
                environment
                    .project()
                    .map(|project| BoundPackageEnvironment::Project(project.clone()))
            }
        }
        None => None,
    };
    Ok(bound.with_package_environment(environment))
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::sync::{Arc, Mutex};

    use super::{RuntimeContextState, abort_runtime_enter, activate_prepared_runtime};
    use crate::{
        environment::{EnvironmentDefinition, SharedEnvironment},
        options::{RuntimeEnvironment, RuntimeOptions, ScriptOptions},
        runtime::{BoundRuntime, DenoRuntime},
        script::ScriptSource,
    };

    fn isolated_bound_runtime(
        folder: &tempfile::TempDir,
    ) -> (
        SharedEnvironment,
        BoundRuntime,
        Arc<Mutex<RuntimeContextState>>,
    ) {
        let definition =
            EnvironmentDefinition::from_mapping(folder.path().to_path_buf(), BTreeMap::new(), None)
                .unwrap();
        let shared = SharedEnvironment::new(definition);
        let runtime = DenoRuntime::new(RuntimeOptions::new_with_js_runtime_options(
            folder.path().to_path_buf(),
            Default::default(),
            Some(RuntimeEnvironment::Isolated(shared.clone())),
        ));
        let script = ScriptSource::from_options(ScriptOptions::inline(
            "export default () => 42;".to_string(),
        ));
        let bound = BoundRuntime::new(runtime, script);
        let context_state = Arc::new(Mutex::new(RuntimeContextState::Entering));
        (shared, bound, context_state)
    }

    #[test]
    fn abort_runtime_enter_closes_active_handle_without_exiting_environment() {
        let folder = tempfile::tempdir().unwrap();
        let (environment, bound, context_state) = isolated_bound_runtime(&folder);
        environment.activate_blocking().unwrap();
        let prepared = super::prepare_bound_runtime(bound).unwrap();
        let (handle, _description) = activate_prepared_runtime(prepared, &context_state);
        assert!(environment.is_active());
        assert!(!handle.is_closed());

        abort_runtime_enter(&context_state);

        assert!(handle.is_closed());
        assert!(environment.is_active());
        environment.deactivate().unwrap();
    }
}
