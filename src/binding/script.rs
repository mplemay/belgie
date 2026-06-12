use pyo3::{Bound, PyAny, PyResult, prelude::*, types::PyType};

use crate::{options::ScriptOptions, script::ScriptSource, utils::normalize_path};

#[pyclass(name = "Script", module = "belgie._core")]
#[derive(Debug)]
pub struct PyScript {
    source: ScriptSource,
}

#[pymethods]
impl PyScript {
    #[new]
    pub fn new(content: String) -> Self {
        Self {
            source: ScriptSource::from_options(ScriptOptions::inline(content)),
        }
    }

    #[classmethod]
    pub fn from_file(_cls: &Bound<'_, PyType>, path: &Bound<'_, PyAny>) -> PyResult<Self> {
        let py = path.py();
        let path = normalize_path::path_from_py(path, "path")?;
        let (path, content) = normalize_path::read_script_file(py, path)?;
        Ok(Self {
            source: ScriptSource::from_options(ScriptOptions::from_file(content, path)),
        })
    }

    fn __repr__(&self) -> String {
        format!("Script({})", self.source.description())
    }
}

impl PyScript {
    pub(crate) fn source(&self) -> ScriptSource {
        self.source.clone()
    }
}
