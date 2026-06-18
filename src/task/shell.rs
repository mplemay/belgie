use std::collections::BTreeMap;
use std::collections::HashMap;
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

use deno_core::anyhow::Context;
use deno_core::error::AnyError;
use deno_task_shell::KillSignal;
use deno_task_shell::ShellPipeReader;
use deno_task_shell::ShellPipeWriter;
use tokio::task::JoinHandle;
use tokio::task::LocalSet;

use crate::packages::PackageEnvironment;
use crate::task::commands::prepare_custom_commands;
use crate::task::types::TaskResult;

pub(crate) const STDERR_CAPTURE_LIMIT: usize = 8 * 1024;
const NPM_CONFIG_USER_AGENT_ENV_VAR: &str = "npm_config_user_agent";

pub(crate) struct TaskStdio(
    pub(crate) Option<ShellPipeReader>,
    pub(crate) ShellPipeWriter,
);

impl TaskStdio {
    pub(crate) fn stdout() -> Self {
        Self(None, ShellPipeWriter::stdout())
    }

    pub(crate) fn stderr() -> Self {
        Self(None, ShellPipeWriter::stderr())
    }

    pub(crate) fn piped() -> Self {
        let (reader, writer) = deno_task_shell::pipe();
        Self(Some(reader), writer)
    }
}

pub(crate) struct TaskIo {
    pub(crate) stdout: TaskStdio,
    pub(crate) stderr: TaskStdio,
}

impl Default for TaskIo {
    fn default() -> Self {
        Self {
            stdout: TaskStdio::stdout(),
            stderr: TaskStdio::stderr(),
        }
    }
}

pub(crate) struct ShellTaskOptions {
    pub(crate) command: String,
    pub(crate) cwd: PathBuf,
    pub(crate) extra_env: BTreeMap<String, String>,
    pub(crate) argv: Vec<String>,
    pub(crate) package_env: PackageEnvironment,
    pub(crate) stdio: TaskIo,
    pub(crate) kill_signal: KillSignal,
}

fn get_script_with_args(script: &str, argv: &[String]) -> String {
    let additional_args = argv
        .iter()
        .map(|argument| format!("'{}'", argument.replace('\'', "'\"'\"'")))
        .collect::<Vec<_>>()
        .join(" ");

    format!("{script} {additional_args}").trim().to_owned()
}

fn real_env_vars() -> HashMap<OsString, OsString> {
    std::env::vars_os()
        .map(|(key, value)| {
            if cfg!(windows) {
                (key.to_ascii_uppercase(), value)
            } else {
                (key, value)
            }
        })
        .collect()
}

fn prepare_env_vars(
    env_vars: &mut HashMap<OsString, OsString>,
    cwd: &Path,
    node_modules_bin_dirs: &[PathBuf],
    extra_env: &BTreeMap<String, String>,
) {
    const INIT_CWD_NAME: &str = "INIT_CWD";
    if !env_vars.contains_key(OsStr::new(INIT_CWD_NAME)) {
        env_vars.insert(INIT_CWD_NAME.into(), cwd.to_path_buf().into_os_string());
    }

    if !env_vars.contains_key(OsStr::new(NPM_CONFIG_USER_AGENT_ENV_VAR)) {
        env_vars.insert(
            NPM_CONFIG_USER_AGENT_ENV_VAR.into(),
            npm_config_user_agent().into(),
        );
    }

    for (key, value) in extra_env {
        env_vars.insert(key.clone().into(), value.clone().into());
    }

    for bin_dir in node_modules_bin_dirs.iter().rev() {
        prepend_to_path(env_vars, bin_dir.as_os_str().to_os_string());
    }
}

fn prepend_to_path(env_vars: &mut HashMap<OsString, OsString>, value: OsString) {
    match env_vars.get_mut(OsStr::new("PATH")) {
        Some(path) => {
            if path.is_empty() {
                *path = value;
            } else {
                let mut new_path = value;
                new_path.push(if cfg!(windows) { ";" } else { ":" });
                new_path.push(&*path);
                *path = new_path;
            }
        }
        None => {
            env_vars.insert("PATH".into(), value);
        }
    }
}

fn npm_config_user_agent() -> String {
    format!(
        "belgie/{} npm/? belgie/{} {} {}",
        env!("CARGO_PKG_VERSION"),
        env!("CARGO_PKG_VERSION"),
        std::env::consts::OS,
        std::env::consts::ARCH,
    )
}

fn read_capped_stderr(reader: ShellPipeReader) -> JoinHandle<Result<Vec<u8>, AnyError>> {
    tokio::task::spawn_blocking(move || {
        let mut reader = reader;
        let mut buffer = Vec::new();
        let mut chunk = [0u8; 1024];
        loop {
            let read = reader.read(&mut chunk)?;
            if read == 0 {
                break;
            }
            let remaining = STDERR_CAPTURE_LIMIT.saturating_sub(buffer.len());
            if remaining > 0 {
                buffer.extend_from_slice(&chunk[..read.min(remaining)]);
            }
        }
        Ok(buffer)
    })
}

pub(crate) async fn run_shell_task(options: ShellTaskOptions) -> Result<TaskResult, AnyError> {
    let script = get_script_with_args(&options.command, &options.argv);
    let seq_list = deno_task_shell::parser::parse(&script)
        .with_context(|| format!("Error parsing script '{}'.", &options.command))?;

    let (custom_commands, node_modules_bin_dirs) =
        prepare_custom_commands(&options.package_env, &options.cwd).await?;

    let mut env_vars = real_env_vars();
    prepare_env_vars(
        &mut env_vars,
        &options.cwd,
        &node_modules_bin_dirs,
        &options.extra_env,
    );

    let state = deno_task_shell::ShellState::new(
        env_vars,
        options.cwd,
        custom_commands,
        options.kill_signal,
    );

    let TaskIo {
        stdout: TaskStdio(_stdout_read, stdout_write),
        stderr: TaskStdio(stderr_read, stderr_write),
    } = options.stdio;

    let stderr = stderr_read.map(read_capped_stderr);

    let local = LocalSet::new();
    let future = async move {
        let exit_code = deno_task_shell::execute_with_pipes(
            seq_list,
            state,
            ShellPipeReader::stdin(),
            stdout_write,
            stderr_write,
        )
        .await;

        let stderr = if let Some(stderr) = stderr {
            stderr.await??
        } else {
            Vec::new()
        };

        Ok::<_, AnyError>(TaskResult {
            exit_code,
            stderr: failure_stderr(exit_code, stderr),
        })
    };

    local.run_until(future).await
}

fn failure_stderr(exit_code: i32, stderr: Vec<u8>) -> Option<String> {
    if exit_code == 0 {
        return None;
    }
    let text = String::from_utf8_lossy(&stderr[..stderr.len().min(STDERR_CAPTURE_LIMIT)]);
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn get_script_with_args_appends_quoted_arguments() {
        assert_eq!(
            get_script_with_args("vite build", &["--outDir".to_string(), "dist".to_string()]),
            "vite build '--outDir' 'dist'"
        );
    }

    #[test]
    fn get_script_with_args_omits_extra_whitespace_without_argv() {
        assert_eq!(get_script_with_args("vite build", &[]), "vite build");
    }

    #[test]
    fn get_script_with_args_escapes_single_quotes() {
        assert_eq!(
            get_script_with_args("echo", &["it's".to_string()]),
            "echo 'it'\"'\"'s'"
        );
    }

    #[test]
    fn failure_stderr_is_none_on_success() {
        assert!(failure_stderr(0, b"warning".to_vec()).is_none());
    }

    #[test]
    fn failure_stderr_includes_failure_output() {
        assert_eq!(
            failure_stderr(1, b"failed".to_vec()).as_deref(),
            Some("failed")
        );
    }

    #[test]
    fn failure_stderr_caps_output_length() {
        let bytes = vec![b'x'; STDERR_CAPTURE_LIMIT * 2];
        assert_eq!(
            failure_stderr(1, bytes).unwrap().len(),
            STDERR_CAPTURE_LIMIT
        );
    }

    #[test]
    fn prepare_env_vars_sets_npm_user_agent_when_absent() {
        let mut env_vars = HashMap::new();
        prepare_env_vars(&mut env_vars, Path::new("/project"), &[], &BTreeMap::new());

        let user_agent = env_vars
            .get(OsStr::new(NPM_CONFIG_USER_AGENT_ENV_VAR))
            .expect("npm user agent should be set");

        assert!(
            user_agent
                .to_string_lossy()
                .starts_with(&format!("belgie/{}", env!("CARGO_PKG_VERSION")))
        );
    }

    #[test]
    fn prepare_env_vars_allows_extra_env_to_override_npm_user_agent() {
        let mut env_vars = HashMap::new();
        let mut extra_env = BTreeMap::new();
        extra_env.insert(
            NPM_CONFIG_USER_AGENT_ENV_VAR.to_string(),
            "custom-agent".to_string(),
        );

        prepare_env_vars(&mut env_vars, Path::new("/project"), &[], &extra_env);

        assert_eq!(
            env_vars
                .get(OsStr::new(NPM_CONFIG_USER_AGENT_ENV_VAR))
                .and_then(|value| value.to_str()),
            Some("custom-agent")
        );
    }
}
