use std::path::PathBuf;

use pyo3::prelude::*;

use crate::runtime::child_process;
use crate::utils::py_error;

#[pyfunction(name = "_run_node_child")]
pub(crate) fn run_node_child(py: Python<'_>, module: PathBuf, argv: Vec<String>) -> PyResult<i32> {
    py.detach(|| child_process::run(module, argv))
        .map_err(py_error::from_binding_error)
}
