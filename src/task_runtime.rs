use std::env;
use std::ffi::{OsStr, OsString};
use std::path::PathBuf;

use deno_core::anyhow::{anyhow, bail};
use deno_core::error::AnyError;
use deno_task_shell::ShellPipeWriter;

use crate::task::{TaskNpmBinOptions, run_task_npm_bin};
use crate::utils::tokio::build_task_runtime;

pub fn run_cli() -> i32 {
    match run_cli_inner() {
        Ok(exit_code) => exit_code,
        Err(error) => {
            eprintln!("{error}");
            1
        }
    }
}

fn run_cli_inner() -> Result<i32, AnyError> {
    let options = parse_args(env::args_os().skip(1))?;
    let runtime = build_task_runtime("npm binary")?;
    Ok(runtime.block_on(run_task_npm_bin(options)))
}

fn parse_args(args: impl IntoIterator<Item = OsString>) -> Result<TaskNpmBinOptions, AnyError> {
    let mut args = args.into_iter();
    let Some(subcommand) = args.next() else {
        bail!("Missing task runtime subcommand");
    };
    if subcommand != OsStr::new("npm-bin") {
        bail!(
            "Unsupported task runtime subcommand: {}",
            subcommand.to_string_lossy()
        );
    }

    let mut project_cwd = None;
    let mut task_cwd = None;
    let mut command_name = None;
    let mut script_path = None;
    let mut argv = Vec::new();

    while let Some(arg) = args.next() {
        if arg == OsStr::new("--") {
            argv = args
                .map(|value| {
                    value.into_string().map_err(|value| {
                        anyhow!(
                            "npm binary arguments must be valid Unicode: {}",
                            value.to_string_lossy()
                        )
                    })
                })
                .collect::<Result<Vec<_>, _>>()?;
            break;
        }

        match arg.to_str() {
            Some("--project-cwd") => project_cwd = Some(next_path(&mut args, "--project-cwd")?),
            Some("--task-cwd") => task_cwd = Some(next_path(&mut args, "--task-cwd")?),
            Some("--command-name") => {
                command_name = Some(next_string(&mut args, "--command-name")?);
            }
            Some("--script-path") => script_path = Some(next_path(&mut args, "--script-path")?),
            Some(flag) => bail!("Unsupported task runtime flag: {flag}"),
            None => bail!(
                "Task runtime flags must be valid Unicode: {}",
                arg.to_string_lossy()
            ),
        }
    }

    Ok(TaskNpmBinOptions {
        project_cwd: project_cwd.ok_or_else(|| anyhow!("Missing --project-cwd"))?,
        task_cwd: task_cwd.ok_or_else(|| anyhow!("Missing --task-cwd"))?,
        command_name: command_name.ok_or_else(|| anyhow!("Missing --command-name"))?,
        script_path: script_path.ok_or_else(|| anyhow!("Missing --script-path"))?,
        argv,
        stdout: ShellPipeWriter::stdout(),
        stderr: ShellPipeWriter::stderr(),
    })
}

fn next_path(args: &mut impl Iterator<Item = OsString>, flag: &str) -> Result<PathBuf, AnyError> {
    args.next()
        .map(PathBuf::from)
        .ok_or_else(|| anyhow!("Missing value for {flag}"))
}

fn next_string(args: &mut impl Iterator<Item = OsString>, flag: &str) -> Result<String, AnyError> {
    let value = args
        .next()
        .ok_or_else(|| anyhow!("Missing value for {flag}"))?;
    value
        .into_string()
        .map_err(|value| anyhow!("{flag} must be valid Unicode: {}", value.to_string_lossy()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_npm_bin_args() {
        let options = parse_args([
            OsString::from("npm-bin"),
            OsString::from("--project-cwd"),
            OsString::from("/project"),
            OsString::from("--task-cwd"),
            OsString::from("/project/app"),
            OsString::from("--command-name"),
            OsString::from("vite"),
            OsString::from("--script-path"),
            OsString::from("/project/node_modules/.bin/vite"),
            OsString::from("--"),
            OsString::from("--outDir"),
            OsString::from("dist"),
        ])
        .expect("arguments should parse");

        assert_eq!(options.project_cwd, PathBuf::from("/project"));
        assert_eq!(options.task_cwd, PathBuf::from("/project/app"));
        assert_eq!(options.command_name, "vite");
        assert_eq!(
            options.script_path,
            PathBuf::from("/project/node_modules/.bin/vite")
        );
        assert_eq!(options.argv, vec!["--outDir", "dist"]);
    }

    #[test]
    fn parse_rejects_missing_subcommand() {
        let Err(error) = parse_args([]) else {
            panic!("missing subcommand should fail");
        };

        assert!(
            error
                .to_string()
                .contains("Missing task runtime subcommand")
        );
    }
}
