use std::{collections::BTreeMap, path::PathBuf};

use pyo3::{PyResult, prelude::*};

use crate::command::CommandSource;

#[pyclass(name = "Command", module = "belgie._core", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PyCommand {
    source: CommandSource,
}

#[pymethods]
impl PyCommand {
    #[new]
    #[pyo3(signature = (name, *, cwd = None, env = None, module = false))]
    fn new(
        name: String,
        cwd: Option<PathBuf>,
        env: Option<BTreeMap<String, String>>,
        module: bool,
    ) -> PyResult<Self> {
        let name = name.trim().to_string();
        if name.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Command name must not be empty",
            ));
        }
        Ok(Self {
            source: CommandSource::new(name, cwd, env.unwrap_or_default(), module),
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "Command(name={:?}, cwd={:?}, env={:?}, module={:?})",
            self.source.name(),
            self.source
                .cwd()
                .map(|path| path.to_string_lossy().into_owned()),
            self.source.env(),
            self.source.module(),
        )
    }
}

impl PyCommand {
    pub(crate) fn source(&self) -> CommandSource {
        self.source.clone()
    }
}
