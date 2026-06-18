use std::collections::BTreeMap;

use pyo3::prelude::*;

#[pyclass(name = "RunTaskOptions", module = "belgie.tasks", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PyRunTaskOptions {
    pub(crate) task_cwd: String,
    pub(crate) script: String,
    pub(crate) argv: Vec<String>,
    pub(crate) env: BTreeMap<String, String>,
    pub(crate) host: Option<String>,
    pub(crate) port: Option<u16>,
    pub(crate) install: bool,
}

#[pymethods]
impl PyRunTaskOptions {
    #[new]
    #[pyo3(signature = (task_cwd, script, *, argv=None, env=None, host=None, port=None, install=false))]
    pub fn new(
        task_cwd: String,
        script: String,
        argv: Option<Vec<String>>,
        env: Option<BTreeMap<String, String>>,
        host: Option<String>,
        port: Option<u16>,
        install: bool,
    ) -> Self {
        Self {
            task_cwd,
            script,
            argv: argv.unwrap_or_default(),
            env: env.unwrap_or_default(),
            host,
            port,
            install,
        }
    }

    #[getter]
    fn task_cwd(&self) -> &str {
        &self.task_cwd
    }

    #[getter]
    fn script(&self) -> &str {
        &self.script
    }

    #[getter]
    fn argv(&self) -> Vec<String> {
        self.argv.clone()
    }

    #[getter]
    fn install(&self) -> bool {
        self.install
    }

    fn __repr__(&self) -> String {
        format!(
            "RunTaskOptions(task_cwd={:?}, script={:?}, argv={:?}, install={})",
            self.task_cwd, self.script, self.argv, self.install
        )
    }
}
