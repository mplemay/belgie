use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use deno_core::anyhow::Context;
use deno_core::error::AnyError;

use crate::packages::PackageEnvironment;
use crate::task::deno_exe::resolve_deno_exe;
use crate::task::types::{RunTaskOptions, TaskResult};

const STDERR_CAPTURE_LIMIT: usize = 8 * 1024;
const TERMINATE_GRACE_PERIOD: Duration = Duration::from_secs(5);

#[derive(Clone, Debug)]
pub(crate) struct TaskProcess {
    inner: Arc<TaskProcessInner>,
}

#[derive(Debug)]
struct TaskProcessInner {
    origin: Option<String>,
    child: Mutex<Option<Child>>,
}

impl TaskProcess {
    pub(crate) fn origin(&self) -> Option<&str> {
        self.inner.origin.as_deref()
    }

    pub(crate) fn is_running_blocking(&self) -> bool {
        let mut guard = self
            .inner
            .child
            .lock()
            .expect("task process child lock should not be poisoned");
        let Some(child) = guard.as_mut() else {
            return false;
        };
        match child.try_wait() {
            Ok(None) => true,
            Ok(Some(_)) => {
                *guard = None;
                false
            }
            Err(_) => {
                *guard = None;
                false
            }
        }
    }

    pub(crate) fn stop_blocking(&self) -> Result<(), AnyError> {
        let mut guard = self
            .inner
            .child
            .lock()
            .expect("task process child lock should not be poisoned");
        let Some(mut child) = guard.take() else {
            return Ok(());
        };
        terminate_child(&mut child)?;
        child
            .wait()
            .context("Failed to wait for task subprocess after stop")?;
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
        let mut child = spawn_deno_task(&options, false)?;
        let status = child.wait().context("Failed to wait for task subprocess")?;
        let exit_code = status.code().unwrap_or(1);
        let stderr = if exit_code == 0 {
            None
        } else {
            read_captured_stderr(&mut child)
        };
        Ok(TaskResult { exit_code, stderr })
    }

    pub(crate) fn start_blocking(&self, options: RunTaskOptions) -> Result<TaskProcess, AnyError> {
        let origin = task_origin(&options);
        let child = spawn_deno_task(&options, true)?;
        Ok(TaskProcess {
            inner: Arc::new(TaskProcessInner {
                origin,
                child: Mutex::new(Some(child)),
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

fn read_captured_stderr(child: &mut Child) -> Option<String> {
    let stderr = child.stderr.take()?;
    let mut buffer = Vec::new();
    stderr
        .take(STDERR_CAPTURE_LIMIT as u64)
        .read_to_end(&mut buffer)
        .ok()?;
    let text = String::from_utf8_lossy(&buffer).trim().to_string();
    if text.is_empty() { None } else { Some(text) }
}

pub(crate) fn build_deno_task_argv(
    options: &RunTaskOptions,
    config_file: &Path,
    lockfile: &Path,
) -> Vec<String> {
    let mut argv = vec![
        "task".to_string(),
        "--config".to_string(),
        config_file.to_string_lossy().into_owned(),
        "--lock".to_string(),
        lockfile.to_string_lossy().into_owned(),
        "--cwd".to_string(),
        options.task_cwd.to_string_lossy().into_owned(),
        options.script.clone(),
    ];
    if !options.argv.is_empty() {
        argv.push("--".to_string());
        argv.extend(options.argv.clone());
    }
    argv
}

fn spawn_deno_task(options: &RunTaskOptions, background: bool) -> Result<Child, AnyError> {
    let env = PackageEnvironment::for_task(&options.task_cwd, &options.script)?;
    let pyproject_dir = env.cwd().to_path_buf();
    let config_file = persist_task_config(&env, &pyproject_dir)?;
    let deno_exe = resolve_deno_exe()?;

    let mut command = Command::new(deno_exe);
    for arg in build_deno_task_argv(options, &config_file, env.lockfile()) {
        command.arg(arg);
    }
    command.current_dir(&pyproject_dir).stdin(Stdio::inherit());

    if background {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
        set_process_group(&mut command);
    } else {
        command.stdout(Stdio::inherit()).stderr(Stdio::piped());
    }

    for (key, value) in &options.env {
        command.env(key, value);
    }

    let child = command
        .spawn()
        .with_context(|| format!("Failed to spawn deno task '{}'", options.script))?;
    Ok(child)
}

fn persist_task_config(
    env: &PackageEnvironment,
    pyproject_dir: &Path,
) -> Result<PathBuf, AnyError> {
    let config_dir = pyproject_dir.join(".belgie");
    fs::create_dir_all(&config_dir)
        .with_context(|| format!("Failed to create {}", config_dir.display()))?;
    let config_file = config_dir.join("deno.json");
    fs::copy(env.config_file(), &config_file).with_context(|| {
        format!(
            "Failed to copy task config from {} to {}",
            env.config_file().display(),
            config_file.display()
        )
    })?;
    Ok(config_file)
}

fn set_process_group(command: &mut Command) {
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
}

fn terminate_child(child: &mut Child) -> Result<(), AnyError> {
    #[cfg(unix)]
    {
        terminate_child_unix(child)
    }
    #[cfg(not(unix))]
    {
        child
            .kill()
            .context("Failed to terminate task subprocess")?;
        Ok(())
    }
}

#[cfg(unix)]
fn terminate_child_unix(child: &mut Child) -> Result<(), AnyError> {
    const SIGTERM: i32 = 15;

    unsafe extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
    }

    let pid = child.id() as i32;
    // SAFETY: kill is a POSIX syscall; negative pid targets the process group.
    let term_result = unsafe { kill(-pid, SIGTERM) };
    if term_result != 0 {
        child
            .kill()
            .context("Failed to terminate task subprocess")?;
        return Ok(());
    }

    let deadline = Instant::now() + TERMINATE_GRACE_PERIOD;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return Ok(()),
            Ok(None) if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(50));
            }
            Ok(None) => break,
            Err(error) => {
                return Err(error).context("Failed to wait for task subprocess after SIGTERM");
            }
        }
    }

    child
        .kill()
        .context("Failed to terminate task subprocess after grace period")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

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
    fn build_deno_task_argv_orders_flags_before_script() {
        let options = sample_options(vec!["--outDir", "dist"]);
        let argv = build_deno_task_argv(
            &options,
            Path::new("/proj/.belgie/deno.json"),
            Path::new("/proj/deno.lock"),
        );

        assert_eq!(
            argv,
            vec![
                "task",
                "--config",
                "/proj/.belgie/deno.json",
                "--lock",
                "/proj/deno.lock",
                "--cwd",
                "/tmp/views",
                "build",
                "--",
                "--outDir",
                "dist",
            ]
        );
    }

    #[test]
    fn build_deno_task_argv_omits_passthrough_without_argv() {
        let options = sample_options(vec![]);
        let argv = build_deno_task_argv(
            &options,
            Path::new("/proj/.belgie/deno.json"),
            Path::new("/proj/deno.lock"),
        );

        assert_eq!(
            argv,
            vec![
                "task",
                "--config",
                "/proj/.belgie/deno.json",
                "--lock",
                "/proj/deno.lock",
                "--cwd",
                "/tmp/views",
                "build",
            ]
        );
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
