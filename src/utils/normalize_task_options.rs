use crate::task::RunTaskOptions;
use crate::types::error::BindingError;

pub(crate) fn normalize_run_task_options(
    mut options: RunTaskOptions,
) -> Result<RunTaskOptions, BindingError> {
    options.script = options.script.trim().to_string();
    if options.script.is_empty() {
        return Err(BindingError::runtime("Task script name must not be empty"));
    }

    options.host = options
        .host
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());

    if let Some(port) = options.port
        && !(1..=65_535).contains(&port)
    {
        return Err(BindingError::runtime(
            "Task port must be an integer between 1 and 65,535",
        ));
    }

    if options.host.is_some() ^ options.port.is_some() {
        return Err(BindingError::runtime(
            "Long-running tasks require both host and port",
        ));
    }

    options.task_cwd = options
        .task_cwd
        .canonicalize()
        .map_err(|error| BindingError::runtime(format!("Invalid task cwd: {error}")))?;

    if !options.task_cwd.is_dir() {
        return Err(BindingError::runtime(format!(
            "Task cwd must be a directory: {}",
            options.task_cwd.display()
        )));
    }

    Ok(options)
}

pub(crate) fn ensure_task_success(result: crate::task::TaskResult) -> Result<(), BindingError> {
    if result.success() {
        return Ok(());
    }

    Err(BindingError::runtime(result.failure_message()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::path::PathBuf;

    #[test]
    fn accepts_missing_host_and_port() {
        let options = normalize_run_task_options(RunTaskOptions {
            task_cwd: PathBuf::from("."),
            script: "idle".to_string(),
            argv: vec![],
            env: BTreeMap::new(),
            host: None,
            port: None,
            install: false,
            python_path: PathBuf::from("/venv/bin/python"),
        })
        .expect("options should normalize");

        assert!(options.host.is_none());
        assert!(options.port.is_none());
    }

    #[test]
    fn rejects_partial_host_and_port() {
        let error = normalize_run_task_options(RunTaskOptions {
            task_cwd: PathBuf::from("."),
            script: "idle".to_string(),
            argv: vec![],
            env: BTreeMap::new(),
            host: Some("127.0.0.1".to_string()),
            port: None,
            install: false,
            python_path: PathBuf::from("/venv/bin/python"),
        })
        .expect_err("partial host/port should fail");

        assert!(error.message().contains("both host and port"));
    }

    #[test]
    fn ensure_task_success_includes_stderr() {
        let error = ensure_task_success(crate::task::TaskResult {
            exit_code: 1,
            stderr: Some("vite failed".to_string()),
        })
        .expect_err("non-zero exit should fail");

        assert!(error.message().contains("status 1"));
        assert!(error.message().contains("vite failed"));
    }
}
