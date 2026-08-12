use std::path::PathBuf;

use pyo3::prelude::*;

use crate::py_error;
use belgie::runtime::child_process;

#[pyfunction(name = "_run_node_child")]
pub(crate) fn run_node_child(py: Python<'_>, module: PathBuf, argv: Vec<String>) -> PyResult<i32> {
    py.detach(|| child_process::run(module, argv))
        .map_err(py_error::from_binding_error)
}
