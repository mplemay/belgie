use pyo3::{
    Bound, PyAny, PyResult, Python, exceptions::PyValueError, prelude::*, types::PyAnyMethods,
};

use crate::{
    binding::{blocking, coerce, packages},
    environment::{EnvironmentDefinition, SharedEnvironment},
    utils::normalize_path,
};

#[pyclass(name = "Environment", module = "belgie._core", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PyEnvironment {
    inner: SharedEnvironment,
}

#[pyclass(name = "SyncEnvironment", module = "belgie._core", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PySyncEnvironment {
    inner: SharedEnvironment,
}

#[pyclass(
    name = "AsyncEnvironment",
    module = "belgie._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyAsyncEnvironment {
    inner: SharedEnvironment,
}

#[pymethods]
impl PyEnvironment {
    #[new]
    #[pyo3(signature = (dependencies = None, *, path = None, lockfile = None))]
    fn new(
        py: Python<'_>,
        dependencies: Option<&Bound<'_, PyAny>>,
        path: Option<&Bound<'_, PyAny>>,
        lockfile: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let dependencies = coerce::normalize_dependencies(dependencies)?;
        if dependencies.is_empty() && lockfile.is_some_and(|value| !value.is_none()) {
            return Err(PyValueError::new_err(
                "lockfile requires at least one dependency mapping",
            ));
        }
        let lockfile = normalize_lockfile_arg(py, lockfile, LockfilePathMode::Input)?;
        let persist_path = normalize_path::normalize_optional_directory(py, path)?;
        let workspace = match &persist_path {
            Some(path) => path.clone(),
            None => normalize_path::normalize_cwd(py, None)?,
        };
        let definition =
            EnvironmentDefinition::from_mapping(workspace, persist_path, dependencies, lockfile)
                .map_err(blocking::any_error_to_py)?;
        Ok(Self {
            inner: SharedEnvironment::new(definition),
        })
    }

    fn __enter__(&self, py: Python<'_>) -> PyResult<PySyncEnvironment> {
        let environment = self.inner.clone();
        py.detach(|| environment.activate_blocking())
            .map_err(blocking::any_error_to_py)?;
        Ok(PySyncEnvironment::new(environment))
    }

    fn __exit__(
        &self,
        _exc_type: Option<&Bound<'_, PyAny>>,
        _exc: Option<&Bound<'_, PyAny>>,
        _traceback: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<bool> {
        self.inner.deactivate().map_err(blocking::any_error_to_py)?;
        Ok(false)
    }

    fn __aenter__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let environment = self.inner.clone();
        let result = PyAsyncEnvironment::new(environment.clone());
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            blocking::run_on_blocking_thread(
                move || environment.activate_blocking().map(|_| ()),
                "Belgie environment activation failed",
            )
            .await?;
            Ok(result)
        })
    }

    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<&Bound<'_, PyAny>>,
        _exc: Option<&Bound<'_, PyAny>>,
        _traceback: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            environment
                .deactivate()
                .map_err(blocking::any_error_to_py)?;
            Ok(false)
        })
    }

    fn __repr__(&self) -> String {
        environment_repr(&self.inner, "Environment")
    }
}

#[pymethods]
impl PySyncEnvironment {
    #[pyo3(signature = (*, lockfile = None))]
    fn lock(
        &self,
        py: Python<'_>,
        lockfile: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<packages::PyEnvironmentInstallResult> {
        let output_lockfile = normalize_lockfile_arg(py, lockfile, LockfilePathMode::Output)?;
        let environment = self.inner.clone();
        py.detach(|| environment.lock_blocking(output_lockfile))
            .map(Into::into)
            .map_err(blocking::any_error_to_py)
    }

    fn install(&self, py: Python<'_>) -> PyResult<packages::PyEnvironmentInstallResult> {
        let environment = self.inner.clone();
        py.detach(|| environment.install_blocking())
            .map(Into::into)
            .map_err(blocking::any_error_to_py)
    }

    #[pyo3(signature = (packages = None, *, latest = false, lockfile_only = false))]
    fn update(
        &self,
        py: Python<'_>,
        packages: Option<&Bound<'_, PyAny>>,
        latest: bool,
        lockfile_only: bool,
    ) -> PyResult<packages::PyEnvironmentUpdateResult> {
        let filters = packages::normalize_package_filters(packages)?;
        let environment = self.inner.clone();
        py.detach(|| environment.update_blocking(filters, latest, lockfile_only))
            .map(Into::into)
            .map_err(blocking::any_error_to_py)
    }

    fn __repr__(&self) -> String {
        environment_repr(&self.inner, "SyncEnvironment")
    }
}

#[pymethods]
impl PyAsyncEnvironment {
    #[pyo3(signature = (*, lockfile = None))]
    fn lock<'py>(
        &self,
        py: Python<'py>,
        lockfile: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let output_lockfile = normalize_lockfile_arg(py, lockfile, LockfilePathMode::Output)?;
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = blocking::run_on_blocking_thread(
                move || environment.lock_blocking(output_lockfile),
                "Belgie environment lock failed",
            )
            .await?;
            Ok(packages::PyEnvironmentInstallResult::from(result))
        })
    }

    fn install<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = blocking::run_on_blocking_thread(
                move || environment.install_blocking(),
                "Belgie environment install failed",
            )
            .await?;
            Ok(packages::PyEnvironmentInstallResult::from(result))
        })
    }

    #[pyo3(signature = (packages = None, *, latest = false, lockfile_only = false))]
    fn update<'py>(
        &self,
        py: Python<'py>,
        packages: Option<&Bound<'_, PyAny>>,
        latest: bool,
        lockfile_only: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = packages::normalize_package_filters(packages)?;
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = blocking::run_on_blocking_thread(
                move || environment.update_blocking(filters, latest, lockfile_only),
                "Belgie environment update failed",
            )
            .await?;
            Ok(packages::PyEnvironmentUpdateResult::from(result))
        })
    }

    fn __repr__(&self) -> String {
        environment_repr(&self.inner, "AsyncEnvironment")
    }
}

impl PyEnvironment {
    pub(crate) fn environment(&self) -> SharedEnvironment {
        self.inner.clone()
    }
}

impl PySyncEnvironment {
    fn new(environment: SharedEnvironment) -> Self {
        Self { inner: environment }
    }

    pub(crate) fn environment(&self) -> SharedEnvironment {
        self.inner.clone()
    }
}

impl PyAsyncEnvironment {
    fn new(environment: SharedEnvironment) -> Self {
        Self { inner: environment }
    }

    pub(crate) fn environment(&self) -> SharedEnvironment {
        self.inner.clone()
    }
}

enum LockfilePathMode {
    Input,
    Output,
}

fn normalize_lockfile_arg(
    py: Python<'_>,
    lockfile: Option<&Bound<'_, PyAny>>,
    mode: LockfilePathMode,
) -> PyResult<Option<std::path::PathBuf>> {
    let Some(lockfile) = lockfile.filter(|value| !value.is_none()) else {
        return Ok(None);
    };
    let path = normalize_path::path_from_py(lockfile, "lockfile")?;
    match mode {
        LockfilePathMode::Input => normalize_path::normalize_file(py, path, "lockfile").map(Some),
        LockfilePathMode::Output => {
            normalize_path::normalize_output_file(py, path, "lockfile").map(Some)
        }
    }
}

fn environment_repr(environment: &SharedEnvironment, class_name: &str) -> String {
    let active = if environment.is_active() {
        "True"
    } else {
        "False"
    };
    match environment.persist_path() {
        Some(path) => format!(
            "{class_name}(path={}, dependencies={}, active={active})",
            path.display(),
            environment.dependency_count(),
        ),
        None => format!(
            "{class_name}(path=None, workspace={}, dependencies={}, active={active})",
            environment.workspace().display(),
            environment.dependency_count(),
        ),
    }
}
