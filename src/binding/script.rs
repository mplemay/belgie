use std::path::PathBuf;

use pyo3::{Bound, PyResult, prelude::*, types::PyType};

use crate::{options::ScriptOptions, script::ScriptSource, utils::normalize_path};

#[pyclass(name = "Script", module = "belgie._core")]
#[derive(Debug)]
pub struct PyScript {
    source: ScriptSource,
}

#[pymethods]
impl PyScript {
    #[new]
    #[pyo3(signature = (content, *, filename = None))]
    pub fn new(content: String, filename: Option<PathBuf>) -> Self {
        Self {
            source: ScriptSource::from_options(ScriptOptions::inline(content, filename)),
        }
    }

    #[classmethod]
    pub fn from_file(_cls: &Bound<'_, PyType>, py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        let (path, content) = normalize_path::read_script_file(py, path)?;
        Ok(Self {
            source: ScriptSource::from_options(ScriptOptions::from_file(content, path)),
        })
    }

    fn __repr__(&self) -> String {
        format!("Script({})", self.source.description())
    }

    #[getter]
    fn content(&self) -> &str {
        self.source.content()
    }

    #[getter]
    fn filename(&self) -> Option<PathBuf> {
        self.source.filename().map(PathBuf::from)
    }
}

impl PyScript {
    pub(crate) fn source(&self) -> ScriptSource {
        self.source.clone()
    }
}
