use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

use deno_core::anyhow::{Context, anyhow};
use deno_core::error::AnyError;
use deno_task_shell::KillSignal;
use deno_task_shell::SignalKind;

use crate::packages::PackageEnvironment;
use crate::task::shell::{ShellTaskOptions, TaskIo, TaskStdio, run_shell_task};
use crate::task::types::{RunTaskOptions, TaskResult};

#[derive(Clone, Debug)]
pub(crate) struct TaskProcess {
    inner: Arc<TaskProcessInner>,
}

#[derive(Debug)]
struct TaskProcessInner {
    origin: Option<String>,
    stop_tx: Mutex<Option<tokio::sync::mpsc::Sender<()>>>,
    join_handle: Mutex<Option<JoinHandle<Result<TaskResult, AnyError>>>>,
    worker_result: Mutex<Option<Result<TaskResult, AnyError>>>,
}

impl TaskProcess {
    pub(crate) fn origin(&self) -> Option<&str> {
        self.inner.origin.as_deref()
    }

    pub(crate) fn is_running_blocking(&self) -> bool {
        collect_worker_if_finished(&self.inner);
        self.inner
            .join_handle
            .lock()
            .expect("task process join handle lock should not be poisoned")
            .is_some()
    }

    pub(crate) fn stop_blocking(&self) -> Result<(), AnyError> {
        if let Some(stop_tx) = self
            .inner
            .stop_tx
            .lock()
            .expect("task process stop lock should not be poisoned")
            .take()
        {
            let _ = stop_tx.blocking_send(());
        }

        collect_worker_if_finished(&self.inner);

        let joined_in_stop = {
            let mut guard = self
                .inner
                .join_handle
                .lock()
                .expect("task process join handle lock should not be poisoned");
            if let Some(handle) = guard.take() {
                *self
                    .inner
                    .worker_result
                    .lock()
                    .expect("task process worker result lock should not be poisoned") =
                    Some(join_worker_handle(handle));
                true
            } else {
                false
            }
        };

        let mut result_guard = self
            .inner
            .worker_result
            .lock()
            .expect("task process worker result lock should not be poisoned");
        if let Some(result) = result_guard.take() {
            match result {
                Err(error) => return Err(error),
                Ok(task_result) if !joined_in_stop => task_failure_error(task_result)?,
                Ok(_) => {}
            }
        }
        Ok(())
    }
}

impl Drop for TaskProcess {
    fn drop(&mut self) {
        let _ = self.stop_blocking();
    }
}

#[derive(Debug, Default)]
pub(crate) struct TaskRunner;

impl TaskRunner {
    pub(crate) fn run_blocking(&self, options: RunTaskOptions) -> Result<TaskResult, AnyError> {
        let (package_env, command) =
            PackageEnvironment::resolve_task(&options.task_cwd, &options.script)?;
        let runtime = build_task_runtime("foreground")?;

        runtime.block_on(run_shell_task(shell_options(
            &options,
            package_env,
            command,
            TaskIo {
                stdout: TaskStdio::stdout(),
                stderr: TaskStdio::piped(),
            },
            KillSignal::default(),
        )))
    }

    pub(crate) fn start_blocking(&self, options: RunTaskOptions) -> Result<TaskProcess, AnyError> {
        PackageEnvironment::resolve_task(&options.task_cwd, &options.script)?;
        let origin = task_origin(&options);
        let (stop_tx, stop_rx) = tokio::sync::mpsc::channel(1);

        let join_handle = thread::spawn(move || {
            let (package_env, command) =
                PackageEnvironment::resolve_task(&options.task_cwd, &options.script)?;
            let runtime = build_task_runtime("background")?;

            runtime.block_on(async move {
                let kill_signal = KillSignal::default();
                let stop_kill_signal = kill_signal.clone();
                let mut stop_rx = stop_rx;
                let mut stopping = false;
                let mut task_fut = std::pin::pin!(run_shell_task(shell_options(
                    &options,
                    package_env,
                    command,
                    TaskIo::default(),
                    kill_signal,
                )));

                loop {
                    tokio::select! {
                        result = task_fut.as_mut() => return result,
                        msg = stop_rx.recv(), if !stopping => {
                            if msg.is_none() {
                                return Err(anyhow!("Background task stop channel closed"));
                            }
                            stopping = true;
                            stop_kill_signal.send(SignalKind::SIGTERM);
                        }
                    }
                }
            })
        });

        Ok(TaskProcess {
            inner: Arc::new(TaskProcessInner {
                origin,
                stop_tx: Mutex::new(Some(stop_tx)),
                join_handle: Mutex::new(Some(join_handle)),
                worker_result: Mutex::new(None),
            }),
        })
    }
}

fn collect_worker_if_finished(inner: &TaskProcessInner) {
    let handle = {
        let mut guard = inner
            .join_handle
            .lock()
            .expect("task process join handle lock should not be poisoned");
        let Some(handle) = guard.as_ref() else {
            return;
        };
        if !handle.is_finished() {
            return;
        }
        guard.take()
    };

    if let Some(handle) = handle {
        let result = join_worker_handle(handle);
        *inner
            .worker_result
            .lock()
            .expect("task process worker result lock should not be poisoned") = Some(result);
    }
}

fn join_worker_handle(
    handle: JoinHandle<Result<TaskResult, AnyError>>,
) -> Result<TaskResult, AnyError> {
    match handle.join() {
        Ok(result) => result,
        Err(_) => Err(anyhow!("Background task thread panicked")),
    }
}

fn task_failure_error(result: TaskResult) -> Result<(), AnyError> {
    if result.success() {
        return Ok(());
    }

    let mut message = format!("Task exited with status {}", result.exit_code);
    if let Some(stderr) = result.stderr {
        message.push_str(":\n");
        message.push_str(&stderr);
    }
    Err(anyhow!(message))
}

fn build_task_runtime(context: &str) -> Result<tokio::runtime::Runtime, AnyError> {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .with_context(|| format!("Failed to create {context} task runtime"))
}

fn shell_options(
    options: &RunTaskOptions,
    package_env: PackageEnvironment,
    command: String,
    stdio: TaskIo,
    kill_signal: KillSignal,
) -> ShellTaskOptions {
    ShellTaskOptions {
        task_name: options.script.clone(),
        command,
        cwd: options.task_cwd.clone(),
        extra_env: options.env.clone(),
        argv: options.argv.clone(),
        package_env,
        stdio,
        kill_signal,
    }
}

fn task_origin(options: &RunTaskOptions) -> Option<String> {
    match (&options.host, options.port) {
        (Some(host), Some(port)) => Some(format!("http://{host}:{port}")),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::path::PathBuf;

    fn sample_options(argv: Vec<&str>) -> RunTaskOptions {
        RunTaskOptions {
            task_cwd: PathBuf::from("/tmp/views"),
            script: "build".to_string(),
            argv: argv.into_iter().map(str::to_string).collect(),
            env: BTreeMap::new(),
            host: None,
            port: None,
        }
    }

    #[test]
    fn task_origin_is_none_without_host_and_port() {
        let options = sample_options(vec![]);
        assert!(task_origin(&options).is_none());
    }

    #[test]
    fn task_origin_includes_host_and_port() {
        let mut options = sample_options(vec![]);
        options.host = Some("127.0.0.1".to_string());
        options.port = Some(13714);
        assert_eq!(
            task_origin(&options).as_deref(),
            Some("http://127.0.0.1:13714")
        );
    }
}
