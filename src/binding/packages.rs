use std::path::PathBuf;

use pyo3::{pyclass, pymethods};

use crate::packages;

#[pyclass(
    name = "EnvironmentInstallResult",
    module = "belgie._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyEnvironmentInstallResult {
    lockfile: PathBuf,
    dependencies: usize,
}

#[pymethods]
impl PyEnvironmentInstallResult {
    #[getter]
    fn lockfile(&self) -> String {
        self.lockfile.to_string_lossy().into_owned()
    }

    #[getter]
    fn dependencies(&self) -> usize {
        self.dependencies
    }

    fn __repr__(&self) -> String {
        format!(
            "EnvironmentInstallResult(lockfile={:?}, dependencies={})",
            self.lockfile(),
            self.dependencies,
        )
    }
}

#[pyclass(
    name = "EnvironmentUpdateChange",
    module = "belgie._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyEnvironmentUpdateChange {
    name: String,
    previous: String,
    updated: String,
}

#[pymethods]
impl PyEnvironmentUpdateChange {
    #[getter]
    fn name(&self) -> &str {
        &self.name
    }

    #[getter]
    fn previous(&self) -> &str {
        &self.previous
    }

    #[getter]
    fn updated(&self) -> &str {
        &self.updated
    }

    fn __repr__(&self) -> String {
        format!(
            "EnvironmentUpdateChange(name={:?}, previous={:?}, updated={:?})",
            self.name, self.previous, self.updated
        )
    }
}

#[pyclass(
    name = "EnvironmentUpdateResult",
    module = "belgie._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyEnvironmentUpdateResult {
    lockfile: PathBuf,
    changes: Vec<PyEnvironmentUpdateChange>,
}

#[pymethods]
impl PyEnvironmentUpdateResult {
    #[getter]
    fn lockfile(&self) -> String {
        self.lockfile.to_string_lossy().into_owned()
    }

    #[getter]
    fn changes(&self) -> Vec<PyEnvironmentUpdateChange> {
        self.changes.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "EnvironmentUpdateResult(lockfile={:?}, changes={})",
            self.lockfile(),
            self.changes.len(),
        )
    }
}

impl From<packages::EnvironmentInstallResult> for PyEnvironmentInstallResult {
    fn from(value: packages::EnvironmentInstallResult) -> Self {
        Self {
            lockfile: value.lockfile,
            dependencies: value.dependencies,
        }
    }
}

impl From<packages::EnvironmentUpdateResult> for PyEnvironmentUpdateResult {
    fn from(value: packages::EnvironmentUpdateResult) -> Self {
        Self {
            lockfile: value.lockfile,
            changes: value.changes.into_iter().map(Into::into).collect(),
        }
    }
}

impl From<packages::EnvironmentUpdateChange> for PyEnvironmentUpdateChange {
    fn from(value: packages::EnvironmentUpdateChange) -> Self {
        Self {
            name: value.name,
            previous: value.previous,
            updated: value.updated,
        }
    }
}
