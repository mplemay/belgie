mod binding;
mod command;
mod embed;
mod environment;
mod exceptions;
mod options;
mod packages;
mod runtime;
mod script;
mod types;
mod utils;

use std::path::PathBuf;

use pyo3::prelude::*;

/// A Python module implemented in Rust. The name of this module must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn _core(py: Python<'_>, m: &pyo3::Bound<'_, pyo3::types::PyModule>) -> pyo3::PyResult<()> {
    let scripts_dir = py
        .import("sysconfig")?
        .call_method1("get_path", ("scripts",))?
        .extract::<PathBuf>()?;
    runtime::child_process::set_executable(
        scripts_dir.join(format!("belgie-runtime{}", std::env::consts::EXE_SUFFIX)),
    );
    m.add_function(wrap_pyfunction!(binding::run_node_child, m)?)?;
    m.add_class::<binding::PyCommand>()?;
    m.add_class::<binding::PyScript>()?;
    m.add_class::<binding::PyEnvironment>()?;
    m.add_class::<binding::PyEnvironmentOptions>()?;
    m.add_class::<binding::PySyncEnvironment>()?;
    m.add_class::<binding::PyAsyncEnvironment>()?;
    m.add_class::<binding::PyRuntime>()?;
    m.add_class::<binding::PyRuntimeOptions>()?;
    m.add_class::<binding::PyRuntimePermissions>()?;
    m.add_class::<binding::PySyncRuntime>()?;
    m.add_class::<binding::PyAsyncRuntime>()?;
    m.add_class::<binding::PySyncRunner>()?;
    m.add_class::<binding::PyAsyncRunner>()?;
    m.add_class::<binding::PySyncCommandRunner>()?;
    m.add_class::<binding::PyAsyncCommandRunner>()?;
    m.add_class::<binding::PyEnvironmentInstallResult>()?;
    m.add_class::<binding::PyEnvironmentUpdateChange>()?;
    m.add_class::<binding::PyEnvironmentUpdateResult>()?;
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
