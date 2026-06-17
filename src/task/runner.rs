use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use deno_core::anyhow::{Context, anyhow};
use deno_core::error::AnyError;
use deno_task_shell::KillSignal;
use deno_task_shell::SignalKind;

use crate::packages::PackageEnvironment;
use crate::task::shell::{ShellTaskOptions, TaskIo, TaskStdio, run_shell_task};
use crate::task::types::{RunTaskOptions, TaskResult};

const TERMINATE_GRACE_PERIOD: Duration = Duration::from_secs(5);
const STOP_JOIN_TIMEOUT: Duration = Duration::from_secs(15);

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
        let was_running = self.is_running_blocking();
        let stop_requested = if let Some(stop_tx) = self
            .inner
            .stop_tx
            .lock()
            .expect("task process stop lock should not be poisoned")
            .take()
        {
            let _ = stop_tx.blocking_send(());
            true
        } else {
            false
        };

        let deadline = Instant::now() + STOP_JOIN_TIMEOUT;
        loop {
            collect_worker_if_finished(&self.inner);
            let has_result = self
                .inner
                .worker_result
                .lock()
                .expect("task process worker result lock should not be poisoned")
                .is_some();
            let has_handle = self
                .inner
                .join_handle
                .lock()
                .expect("task process join handle lock should not be poisoned")
                .is_some();
            if has_result || !has_handle {
                break;
            }
            if Instant::now() >= deadline {
                return Err(anyhow!("Background task did not stop within timeout"));
            }
            std::thread::sleep(Duration::from_millis(50));
        }

        let mut result_guard = self
            .inner
            .worker_result
            .lock()
            .expect("task process worker result lock should not be poisoned");
        if let Some(result) = result_guard.take() {
            match result {
                Err(error) => return Err(error),
                Ok(task_result)
                    if stop_requested && (was_running || task_result.exit_code >= 128) => {}
                Ok(task_result) => {
                    if !task_result.success() {
                        return Err(anyhow!(task_result.failure_message()));
                    }
                }
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
            PackageEnvironment::resolve_task(&options.task_cwd, &options.script, options.install)?;
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
        let (pyproject_dir, dependencies, command) =
            PackageEnvironment::validate_task(&options.task_cwd, &options.script, options.install)?;
        let origin = task_origin(&options);
        let (stop_tx, stop_rx) = tokio::sync::mpsc::channel(1);

        let join_handle = thread::spawn(move || {
            let (package_env, command) = PackageEnvironment::resolve_task_from_parts(
                pyproject_dir,
                dependencies,
                command,
                options.install,
            )?;
            let runtime = build_task_runtime("background")?;

            runtime.block_on(async move {
                use tokio::time::{Instant as TokioInstant, sleep};

                let kill_signal = KillSignal::default();
                let stop_kill_signal = kill_signal.clone();
                let mut stop_rx = stop_rx;
                let mut stopping = false;
                let mut escalated = false;
                let mut grace_deadline = None;
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
                            // deno_task_shell signals individual child PIDs, not POSIX process groups.
                            stop_kill_signal.send(SignalKind::SIGTERM);
                            grace_deadline = Some(TokioInstant::now() + TERMINATE_GRACE_PERIOD);
                        }
                        _ = sleep(Duration::from_millis(50)), if stopping && !escalated => {
                            if grace_deadline.is_some_and(|deadline| TokioInstant::now() >= deadline) {
                                stop_kill_signal.send(SignalKind::SIGKILL);
                                escalated = true;
                            }
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
            install: false,
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

    #[cfg(unix)]
    #[test]
    fn background_stop_escalates_after_grace_period() {
        use std::fs;

        use crate::packages::EMPTY_DENO_LOCK;

        let root = tempfile::tempdir().unwrap();
        let project = root.path().join("project");
        fs::create_dir_all(&project).unwrap();
        let heartbeat = project.join("heartbeat");
        let script = format!(
            "sh -c \"trap '' TERM; while true; do echo tick >> \\\"{}\\\"; sleep 0.05; done\"",
            heartbeat.display()
        );
        fs::write(
            project.join("pyproject.toml"),
            format!(
                "[belgie.dependencies]\nstub = \"jsr:@std/assert@^1\"\n\n[belgie.scripts]\nserve = {}\n",
                serde_json::to_string(&script).unwrap()
            ),
        )
        .unwrap();
        fs::write(project.join("deno.lock"), EMPTY_DENO_LOCK).unwrap();

        let options = RunTaskOptions {
            task_cwd: project.canonicalize().unwrap(),
            script: "serve".to_string(),
            argv: Vec::new(),
            env: BTreeMap::new(),
            host: None,
            port: None,
            install: false,
        };

        let process = TaskRunner.start_blocking(options).unwrap();

        let deadline = Instant::now() + Duration::from_secs(2);
        while !heartbeat.exists() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(heartbeat.exists());

        process.stop_blocking().unwrap();

        let len_after_stop = fs::metadata(&heartbeat).unwrap().len();
        std::thread::sleep(Duration::from_millis(200));
        assert_eq!(fs::metadata(&heartbeat).unwrap().len(), len_after_stop);
    }
}
