use pyo3::prelude::*;
use std::path::PathBuf;

use crate::{
    binding::task_process::PyTaskProcess,
    binding::{blocking, task_options::PyRunTaskOptions},
    task::TaskRunner,
    utils::normalize_task_options::{ensure_task_success, normalize_run_task_options},
    utils::py_error,
};

#[pyclass(name = "TaskRunner", module = "belgie.tasks")]
#[derive(Debug, Default)]
pub(crate) struct PyTaskRunner;

#[pymethods]
impl PyTaskRunner {
    #[new]
    fn new() -> Self {
        Self
    }

    fn run<'py>(
        &self,
        py: Python<'py>,
        options: PyRef<'_, PyRunTaskOptions>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let normalized = normalized_options_from_py(options)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = blocking::run_on_blocking_thread(
                move || TaskRunner.run_blocking(normalized),
                "Task run failed",
            )
            .await?;
            ensure_task_success(result).map_err(py_error::from_binding_error)
        })
    }

    fn start<'py>(
        &self,
        py: Python<'py>,
        options: PyRef<'_, PyRunTaskOptions>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let normalized = normalized_options_from_py(options)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            blocking::run_on_blocking_thread(
                move || TaskRunner.start_blocking(normalized),
                "Task start failed",
            )
            .await
            .map(PyTaskProcess::new)
        })
    }

    fn __repr__(&self) -> &'static str {
        "TaskRunner()"
    }
}

fn normalized_options_from_py(
    options: PyRef<'_, PyRunTaskOptions>,
) -> PyResult<crate::task::RunTaskOptions> {
    let task_cwd = std::path::PathBuf::from(&options.task_cwd);
    normalize_run_task_options(crate::task::RunTaskOptions {
        task_cwd,
        script: options.script.clone(),
        argv: options.argv.clone(),
        env: options.env.clone(),
        host: options.host.clone(),
        port: options.port,
        install: options.install,
    })
    .map_err(py_error::from_binding_error)
}

#[pyfunction(name = "_run_task_npm_bin")]
pub(crate) fn py_run_task_npm_bin(
    project_cwd: PathBuf,
    task_cwd: PathBuf,
    command_name: String,
    script_path: PathBuf,
    argv: Vec<String>,
) -> PyResult<i32> {
    crate::utils::tokio::run_outside_runtime(|| {
        let runtime = crate::utils::tokio::build_task_runtime("npm bin task")?;
        runtime.block_on(crate::task::run_task_npm_bin(
            project_cwd,
            task_cwd,
            command_name,
            script_path,
            argv,
        ))
    })
    .map_err(blocking::any_error_to_py)
}
