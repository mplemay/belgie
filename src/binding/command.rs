use std::collections::BTreeMap;

use pyo3::{Bound, PyAny, PyResult, prelude::*};

use crate::{command::CommandSource, utils::normalize_path};

#[pyclass(name = "Command", module = "belgie._core", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PyCommand {
    source: CommandSource,
}

#[pymethods]
impl PyCommand {
    #[new]
    #[pyo3(signature = (name, *, cwd = None, env = None))]
    fn new(
        name: String,
        cwd: Option<&Bound<'_, PyAny>>,
        env: Option<BTreeMap<String, String>>,
    ) -> PyResult<Self> {
        let name = name.trim().to_string();
        if name.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Command name must not be empty",
            ));
        }
        let cwd = cwd
            .filter(|value| !value.is_none())
            .map(|value| normalize_path::path_from_py(value, "cwd"))
            .transpose()?;
        Ok(Self {
            source: CommandSource::new(name, cwd, env.unwrap_or_default()),
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "Command(name={:?}, cwd={:?}, env={:?})",
            self.source.name(),
            self.source
                .cwd()
                .map(|path| path.to_string_lossy().into_owned()),
            self.source.env(),
        )
    }
}

impl PyCommand {
    pub(crate) fn source(&self) -> CommandSource {
        self.source.clone()
    }
}
