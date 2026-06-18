mod binding;
mod embed;
mod environment;
mod exceptions;
mod options;
mod packages;
mod runtime;
mod script;
mod task;
pub mod task_runtime;
mod types;
mod utils;

use pyo3::prelude::*;

/// A Python module implemented in Rust. The name of this module must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn _core(py: Python<'_>, m: &pyo3::Bound<'_, pyo3::types::PyModule>) -> pyo3::PyResult<()> {
    m.add_class::<binding::PyScript>()?;
    m.add_class::<binding::PyEnvironment>()?;
    m.add_class::<binding::PyRuntime>()?;
    m.add_class::<binding::PyRuntimeOptions>()?;
    m.add_class::<binding::PySyncRunner>()?;
    m.add_class::<binding::PyAsyncRunner>()?;
    m.add_class::<binding::PyPackageInstallResult>()?;
    m.add_class::<binding::PyPackageUpdateChange>()?;
    m.add_class::<binding::PyPackageUpdateResult>()?;
    m.add_class::<binding::PyTaskRunner>()?;
    m.add_class::<binding::PyRunTaskOptions>()?;
    m.add_class::<binding::PyTaskProcess>()?;
    m.add_function(wrap_pyfunction!(binding::py_install, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_lock, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_update, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_ainstall, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_alock, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_aupdate, m)?)?;
    m.add_function(wrap_pyfunction!(binding::py_configure_task_runtime, m)?)?;
    m.add("BelgieError", py.get_type::<exceptions::BelgieError>())?;
    m.add(
        "BelgieRuntimeError",
        py.get_type::<exceptions::BelgieRuntimeError>(),
    )?;
    m.add(
        "BelgieModuleError",
        py.get_type::<exceptions::BelgieModuleError>(),
    )?;
    m.add(
        "BelgieJavaScriptError",
        py.get_type::<exceptions::BelgieJavaScriptError>(),
    )?;
    Ok(())
}
