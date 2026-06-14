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
}

impl TaskProcess {
    pub(crate) fn origin(&self) -> Option<&str> {
        self.inner.origin.as_deref()
    }

    pub(crate) fn is_running_blocking(&self) -> bool {
        let mut guard = self
            .inner
            .join_handle
            .lock()
            .expect("task process join handle lock should not be poisoned");
        let Some(handle) = guard.as_ref() else {
            return false;
        };
        if handle.is_finished() {
            *guard = None;
            false
        } else {
            true
        }
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

        let mut guard = self
            .inner
            .join_handle
            .lock()
            .expect("task process join handle lock should not be poisoned");
        if let Some(handle) = guard.take() {
            handle
                .join()
                .map_err(|_| anyhow!("Background task thread panicked"))??;
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
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .context("Failed to create task runtime")?;

        runtime.block_on(run_shell_task(ShellTaskOptions {
            task_name: options.script.clone(),
            command,
            cwd: options.task_cwd.clone(),
            init_cwd: options.task_cwd.clone(),
            extra_env: options.env.clone(),
            argv: options.argv.clone(),
            package_env,
            stdio: Some(TaskIo {
                stdout: TaskStdio::stdout(),
                stderr: TaskStdio::piped(),
            }),
            kill_signal: KillSignal::default(),
        }))
    }

    pub(crate) fn start_blocking(&self, options: RunTaskOptions) -> Result<TaskProcess, AnyError> {
        let origin = task_origin(&options);
        let task_cwd = options.task_cwd.clone();
        let script = options.script.clone();
        let argv = options.argv.clone();
        let env = options.env.clone();
        let (stop_tx, stop_rx) = tokio::sync::mpsc::channel(1);

        let join_handle = thread::spawn(move || {
            let (package_env, command) = PackageEnvironment::resolve_task(&task_cwd, &script)?;
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .context("Failed to create background task runtime")?;

            runtime.block_on(async move {
                let kill_signal = KillSignal::default();
                let stop_kill_signal = kill_signal.clone();
                let mut stop_rx = stop_rx;
                let mut stopping = false;
                let mut task_fut = std::pin::pin!(run_shell_task(ShellTaskOptions {
                    task_name: script,
                    command,
                    cwd: task_cwd.clone(),
                    init_cwd: task_cwd,
                    extra_env: env,
                    argv,
                    package_env,
                    stdio: None,
                    kill_signal,
                }));

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
            }),
        })
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
