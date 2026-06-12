use std::collections::BTreeMap;
use std::path::PathBuf;

use crate::task::RunTaskOptions;
use crate::types::error::BindingError;

pub(crate) fn normalize_run_task_options(
    task_cwd: PathBuf,
    script: String,
    argv: Vec<String>,
    env: BTreeMap<String, String>,
    host: Option<String>,
    port: Option<u16>,
) -> Result<RunTaskOptions, BindingError> {
    let script = script.trim().to_string();
    if script.is_empty() {
        return Err(BindingError::runtime("Task script name must not be empty"));
    }

    let host = host
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());

    if let Some(port) = port
        && !(1..=65_535).contains(&port)
    {
        return Err(BindingError::runtime(
            "Task port must be an integer between 1 and 65,535",
        ));
    }

    if host.is_some() ^ port.is_some() {
        return Err(BindingError::runtime(
            "Long-running tasks require both host and port",
        ));
    }

    let task_cwd = task_cwd
        .canonicalize()
        .map_err(|error| BindingError::runtime(format!("Invalid task cwd: {error}")))?;

    if !task_cwd.is_dir() {
        return Err(BindingError::runtime(format!(
            "Task cwd must be a directory: {}",
            task_cwd.display()
        )));
    }

    Ok(RunTaskOptions {
        task_cwd,
        script,
        argv,
        env,
        host,
        port,
    })
}

pub(crate) fn ensure_task_success(result: crate::task::TaskResult) -> Result<(), BindingError> {
    if result.success() {
        return Ok(());
    }

    let mut message = format!("Task exited with status {}", result.exit_code);
    if let Some(stderr) = result.stderr {
        message.push_str(":\n");
        message.push_str(&stderr);
    }
    Err(BindingError::runtime(message))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn accepts_missing_host_and_port() {
        let options = normalize_run_task_options(
            PathBuf::from("."),
            "idle".to_string(),
            vec![],
            BTreeMap::new(),
            None,
            None,
        )
        .expect("options should normalize");

        assert!(options.host.is_none());
        assert!(options.port.is_none());
    }

    #[test]
    fn rejects_partial_host_and_port() {
        let error = normalize_run_task_options(
            PathBuf::from("."),
            "idle".to_string(),
            vec![],
            BTreeMap::new(),
            Some("127.0.0.1".to_string()),
            None,
        )
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
