use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use deno_core::anyhow::Context;
use deno_core::error::AnyError;
use tempfile::TempDir;

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
    config_dir: TempDir,
}

#[derive(Debug)]
struct SpawnedTask {
    child: Child,
    config_dir: TempDir,
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
        let _ = self.inner.config_dir.path();
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
        wait_for_foreground_child(spawn_deno_task(&options, false)?)
    }

    pub(crate) fn start_blocking(&self, options: RunTaskOptions) -> Result<TaskProcess, AnyError> {
        let origin = task_origin(&options);
        let SpawnedTask { child, config_dir } = spawn_deno_task(&options, true)?;
        Ok(TaskProcess {
            inner: Arc::new(TaskProcessInner {
                origin,
                child: Mutex::new(Some(child)),
                config_dir,
            }),
        })
    }
}

fn wait_for_foreground_child(mut task: SpawnedTask) -> Result<TaskResult, AnyError> {
    let stderr_reader = task.child.stderr.take().map(spawn_captured_stderr_reader);
    let status = task
        .child
        .wait()
        .context("Failed to wait for task subprocess")?;
    let exit_code = status.code().unwrap_or(1);
    let captured_stderr = stderr_reader
        .and_then(|reader| reader.join().ok())
        .flatten();
    let stderr = if exit_code == 0 {
        None
    } else {
        captured_stderr
    };
    Ok(TaskResult { exit_code, stderr })
}

fn spawn_captured_stderr_reader(stderr: impl Read + Send + 'static) -> JoinHandle<Option<String>> {
    thread::spawn(move || read_captured_stderr(stderr))
}

fn task_origin(options: &RunTaskOptions) -> Option<String> {
    match (&options.host, options.port) {
        (Some(host), Some(port)) => Some(format!("http://{host}:{port}")),
        _ => None,
    }
}

fn read_captured_stderr(mut stderr: impl Read) -> Option<String> {
    let mut buffer = Vec::new();
    let mut chunk = [0; 1024];
    loop {
        let read = stderr.read(&mut chunk).ok()?;
        if read == 0 {
            break;
        }
        let remaining = STDERR_CAPTURE_LIMIT.saturating_sub(buffer.len());
        if remaining > 0 {
            buffer.extend_from_slice(&chunk[..read.min(remaining)]);
        }
    }
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

fn spawn_deno_task(options: &RunTaskOptions, background: bool) -> Result<SpawnedTask, AnyError> {
    let env = PackageEnvironment::for_task(&options.task_cwd, &options.script)?;
    let pyproject_dir = env.cwd().to_path_buf();
    let (config_dir, config_file) = copy_task_config_to_temp_dir(&env)?;
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
    Ok(SpawnedTask { child, config_dir })
}

fn copy_task_config_to_temp_dir(env: &PackageEnvironment) -> Result<(TempDir, PathBuf), AnyError> {
    let config_dir = tempfile::Builder::new()
        .prefix("belgie-task-")
        .tempdir()
        .context("Failed to create temporary Deno task config directory")?;
    let config_file = config_dir.path().join("deno.json");
    fs::copy(env.config_file(), &config_file).with_context(|| {
        format!(
            "Failed to copy task config from {} to {}",
            env.config_file().display(),
            config_file.display()
        )
    })?;
    Ok((config_dir, config_file))
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
    terminate_child_unix_with_grace(child, TERMINATE_GRACE_PERIOD)
}

#[cfg(unix)]
fn terminate_child_unix_with_grace(
    child: &mut Child,
    grace_period: Duration,
) -> Result<(), AnyError> {
    const SIGTERM: i32 = 15;
    const SIGKILL: i32 = 9;

    let pid = child.id() as i32;
    if signal_process_group(pid, SIGTERM).is_err() {
        child
            .kill()
            .context("Failed to terminate task subprocess")?;
        return Ok(());
    }

    let deadline = Instant::now() + grace_period;
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

    if child
        .try_wait()
        .context("Failed to wait for task subprocess before SIGKILL")?
        .is_some()
    {
        return Ok(());
    }
    if signal_process_group(pid, SIGKILL).is_err() {
        child
            .kill()
            .context("Failed to terminate task subprocess after grace period")?;
    }
    Ok(())
}

#[cfg(unix)]
fn signal_process_group(pid: i32, signal: i32) -> std::io::Result<()> {
    unsafe extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
    }

    // SAFETY: kill is a POSIX syscall; negative pid targets the process group.
    let result = unsafe { kill(-pid, signal) };
    if result == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::io::Write;

    const LARGE_STDERR_CHILD_ENV: &str = "BELGIE_LARGE_STDERR_CHILD";

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

    #[cfg(unix)]
    fn shell_quote(value: &Path) -> String {
        format!("'{}'", value.to_string_lossy().replace('\'', "'\\''"))
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

    #[test]
    fn task_config_is_copied_to_temp_dir_not_project() {
        let root = tempfile::tempdir().unwrap();
        let project = root.path().join("project");
        fs::create_dir_all(&project).unwrap();
        fs::write(
            project.join("pyproject.toml"),
            r#"[belgie]

[belgie.scripts]
build = "echo ok"
"#,
        )
        .unwrap();
        let env = PackageEnvironment::for_task(&project, "build").unwrap();

        let (config_dir, config_file) = copy_task_config_to_temp_dir(&env).unwrap();

        assert!(config_file.starts_with(config_dir.path()));
        assert!(config_file.is_file());
        assert!(!project.join(".belgie").exists());
    }

    #[test]
    fn drains_foreground_task_stderr_before_waiting() {
        let child = Command::new(std::env::current_exe().unwrap())
            .arg("foreground_task_stderr_writer_child")
            .arg("--nocapture")
            .env(LARGE_STDERR_CHILD_ENV, "1")
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let task = SpawnedTask {
            child,
            config_dir: tempfile::tempdir().unwrap(),
        };

        let result = wait_for_foreground_child(task).unwrap();

        assert_eq!(result.exit_code, 7);
        assert_eq!(result.stderr.unwrap().len(), STDERR_CAPTURE_LIMIT);
    }

    #[test]
    fn foreground_task_stderr_writer_child() {
        if std::env::var_os(LARGE_STDERR_CHILD_ENV).is_none() {
            return;
        }

        let stderr = vec![b'x'; STDERR_CAPTURE_LIMIT * 4];
        std::io::stderr().write_all(&stderr).unwrap();
        std::process::exit(7);
    }

    #[cfg(unix)]
    #[test]
    fn unix_termination_kills_process_group_after_grace_period() {
        let root = tempfile::tempdir().unwrap();
        let heartbeat = root.path().join("heartbeat");
        let heartbeat_arg = shell_quote(&heartbeat);
        let script = format!(
            "trap '' TERM; (trap '' TERM; while true; do echo tick >> {heartbeat_arg}; sleep 0.05; done) & wait"
        );
        let mut command = Command::new("sh");
        command
            .arg("-c")
            .arg(script)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        set_process_group(&mut command);
        let mut child = command.spawn().unwrap();

        let deadline = Instant::now() + Duration::from_secs(2);
        while !heartbeat.exists() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(heartbeat.exists());

        terminate_child_unix_with_grace(&mut child, Duration::from_millis(50)).unwrap();
        child.wait().unwrap();
        let len_after_stop = fs::metadata(&heartbeat).unwrap().len();
        std::thread::sleep(Duration::from_millis(200));

        assert_eq!(fs::metadata(&heartbeat).unwrap().len(), len_after_stop);
    }
}
