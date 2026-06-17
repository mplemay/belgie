use std::collections::BTreeMap;

use pyo3::{
    Bound, PyAny, PyResult, Python,
    exceptions::PyValueError,
    prelude::*,
    types::{PyAnyMethods, PyType},
};

use crate::{
    binding::blocking,
    environment::{EnvironmentDefinition, SharedEnvironment},
    utils::normalize_path,
};

#[pyclass(name = "Environment", module = "belgie._core", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PyEnvironment {
    inner: SharedEnvironment,
}

#[pymethods]
impl PyEnvironment {
    #[new]
    #[pyo3(signature = (dependencies = None, *, lockfile = None))]
    fn new(
        py: Python<'_>,
        dependencies: Option<&Bound<'_, PyAny>>,
        lockfile: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let dependencies = normalize_dependencies(py, dependencies)?;
        if dependencies.is_empty() && lockfile.is_some_and(|value| !value.is_none()) {
            return Err(PyValueError::new_err(
                "lockfile requires at least one dependency mapping",
            ));
        }
        let lockfile = normalize_lockfile(py, lockfile)?;
        let cwd = normalize_path::normalize_cwd(py, None)?;
        let definition = EnvironmentDefinition::from_mapping(cwd, dependencies, lockfile)
            .map_err(blocking::any_error_to_py)?;
        Ok(Self {
            inner: SharedEnvironment::new(definition),
        })
    }

    #[classmethod]
    #[pyo3(signature = (path, *, groups = None))]
    fn from_folder(
        _cls: &Bound<'_, PyType>,
        path: &Bound<'_, PyAny>,
        groups: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let py = path.py();
        let path = normalize_path::path_from_py(path, "path")?;
        let path = normalize_path::normalize_directory(py, path, "path")?;
        let groups = normalize_groups(py, groups)?;
        let definition =
            EnvironmentDefinition::from_folder(path, groups).map_err(blocking::any_error_to_py)?;
        Ok(Self {
            inner: SharedEnvironment::new(definition),
        })
    }

    fn __enter__(&self, py: Python<'_>) -> PyResult<Self> {
        let environment = self.inner.clone();
        py.detach(|| environment.activate_blocking())
            .map_err(blocking::any_error_to_py)?;
        Ok(self.clone())
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
        let result = self.clone();
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
        let active = if self.inner.is_active() {
            "True"
        } else {
            "False"
        };
        format!(
            "Environment(cwd={}, dependencies={}, active={active})",
            self.inner.cwd().display(),
            self.inner.dependency_count(),
        )
    }
}

impl PyEnvironment {
    pub(crate) fn environment(&self) -> SharedEnvironment {
        self.inner.clone()
    }
}

fn normalize_dependencies(
    py: Python<'_>,
    dependencies: Option<&Bound<'_, PyAny>>,
) -> PyResult<BTreeMap<String, String>> {
    let Some(dependencies) = dependencies.filter(|value| !value.is_none()) else {
        return Ok(BTreeMap::new());
    };
    py.import("builtins")?
        .getattr("dict")?
        .call1((dependencies,))?
        .extract()
}

fn normalize_lockfile(
    py: Python<'_>,
    lockfile: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<std::path::PathBuf>> {
    let Some(lockfile) = lockfile.filter(|value| !value.is_none()) else {
        return Ok(None);
    };
    let path = normalize_path::path_from_py(lockfile, "lockfile")?;
    normalize_path::normalize_file(py, path, "lockfile").map(Some)
}

pub(crate) fn normalize_groups(
    py: Python<'_>,
    groups: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<Vec<String>>> {
    let Some(groups) = groups.filter(|value| !value.is_none()) else {
        return Ok(None);
    };
    py.import("builtins")?
        .getattr("list")?
        .call1((groups,))?
        .extract()
        .map(Some)
}
