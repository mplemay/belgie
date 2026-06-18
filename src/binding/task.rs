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
        let normalized = normalized_options_from_py(py, options)?;
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
        let normalized = normalized_options_from_py(py, options)?;
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

#[pyfunction(name = "_run_task_module")]
pub(crate) fn py_run_task_module(
    py: Python<'_>,
    project_dir: String,
    config_file: String,
    lockfile: String,
    command_name: String,
    module_path: String,
    argv: Vec<String>,
) -> PyResult<i32> {
    py.detach(|| {
        crate::utils::tokio::run_outside_runtime(|| {
            crate::task::run_npm_binary_blocking(
                PathBuf::from(project_dir),
                PathBuf::from(config_file),
                PathBuf::from(lockfile),
                command_name,
                PathBuf::from(module_path),
                argv,
            )
        })
    })
    .map_err(blocking::any_error_to_py)
}

fn normalized_options_from_py(
    py: Python<'_>,
    options: PyRef<'_, PyRunTaskOptions>,
) -> PyResult<crate::task::RunTaskOptions> {
    let task_cwd = std::path::PathBuf::from(&options.task_cwd);
    let python_path = PathBuf::from(
        py.import("sys")?
            .getattr("executable")?
            .extract::<String>()?,
    );
    normalize_run_task_options(crate::task::RunTaskOptions {
        task_cwd,
        script: options.script.clone(),
        argv: options.argv.clone(),
        env: options.env.clone(),
        host: options.host.clone(),
        port: options.port,
        install: options.install,
        python_path,
    })
    .map_err(py_error::from_binding_error)
}
