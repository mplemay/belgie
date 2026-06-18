use std::collections::HashMap;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use deno_core::anyhow::Context;
use deno_core::error::AnyError;
use deno_core::futures::future::LocalBoxFuture;
use deno_resolver::npm::ManagedNpmResolver;
use deno_resolver::npm::NpmResolver;
use deno_task_shell::ExecutableCommand;
use deno_task_shell::ExecuteResult;
use deno_task_shell::ShellCommand;
use deno_task_shell::ShellCommandContext;
use node_resolver::DenoIsBuiltInNodeModuleChecker;
use node_resolver::NodeResolver;

use crate::embed::sys::EmbedSys;
use crate::packages::{PackageEnvironment, project_state_error};

type EmbedNodeResolver = NodeResolver<
    deno_resolver::npm::DenoInNpmPackageChecker,
    DenoIsBuiltInNodeModuleChecker,
    NpmResolver<EmbedSys>,
    EmbedSys,
>;

#[derive(Clone)]
struct NodeModulesFileRunCommand {
    command_name: String,
    project_cwd: PathBuf,
    path: PathBuf,
    python_exe: PathBuf,
}

impl ShellCommand for NodeModulesFileRunCommand {
    fn execute(&self, context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let task_cwd = context.state.cwd().clone();
        let args = task_bin_helper_args(
            &self.project_cwd,
            &task_cwd,
            &self.command_name,
            &self.path,
            context.args,
        );
        ExecutableCommand::new("python".to_string(), self.python_exe.clone())
            .execute(ShellCommandContext { args, ..context })
    }
}

fn task_bin_helper_args(
    project_cwd: &Path,
    task_cwd: &Path,
    command_name: &str,
    path: &Path,
    forwarded_args: Vec<OsString>,
) -> Vec<OsString> {
    let mut args = vec![
        OsString::from("-m"),
        OsString::from("belgie._task_runtime"),
        OsString::from("npm-bin"),
        OsString::from("--project-cwd"),
        project_cwd.as_os_str().to_os_string(),
        OsString::from("--cwd"),
        task_cwd.as_os_str().to_os_string(),
        OsString::from("--command-name"),
        OsString::from(command_name),
        OsString::from("--"),
        path.as_os_str().to_os_string(),
    ];
    args.extend(forwarded_args);
    args
}

impl NodeModulesFileRunCommand {
    fn new(command_name: String, path: PathBuf, project_cwd: &Path, python_exe: PathBuf) -> Self {
        Self {
            command_name,
            project_cwd: project_cwd.to_path_buf(),
            path,
            python_exe,
        }
    }
}

struct NodeCommand;

impl ShellCommand for NodeCommand {
    fn execute(&self, mut context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let node_path = match context.state.resolve_command_path("node".as_ref()) {
            Ok(path) => path,
            Err(error) => {
                let _ = context.stderr.write_line(&format!("{error}"));
                return Box::pin(std::future::ready(ExecuteResult::from_exit_code(
                    error.exit_code(),
                )));
            }
        };
        let args = context.args;
        ExecutableCommand::new("node".to_string(), node_path)
            .execute(ShellCommandContext { args, ..context })
    }
}

struct UnsupportedDenoCommand;

impl ShellCommand for UnsupportedDenoCommand {
    fn execute(&self, mut context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let _ = context.stderr.write_line(
            "The 'deno' command is not supported in Belgie tasks. Use an installed npm package binary or an ordinary shell command.",
        );
        Box::pin(std::future::ready(ExecuteResult::from_exit_code(1)))
    }
}

pub(crate) async fn prepare_custom_commands(
    package_env: &PackageEnvironment,
    cwd: &Path,
) -> Result<(HashMap<String, Rc<dyn ShellCommand>>, Vec<PathBuf>), AnyError> {
    let context = package_env.embed_context().map_err(project_state_error)?;
    context
        .npm_installer_factory()
        .initialize_npm_resolution_if_managed()
        .await
        .map_err(project_state_error)?;

    let node_resolver = context
        .resolver_factory()
        .node_resolver()
        .map_err(project_state_error)?;
    let npm_resolver = context
        .resolver_factory()
        .npm_resolver()
        .map_err(project_state_error)?;
    let bin_dirs = resolve_task_node_modules_bin_dirs(npm_resolver, cwd);
    let python_exe = std::env::current_exe()
        .with_context(|| "Could not resolve current Python executable for Belgie task runtime")?;

    let mut commands = match npm_resolver {
        NpmResolver::Byonm(_) => {
            resolve_byonm_npm_commands(node_resolver, &bin_dirs, package_env.cwd(), &python_exe)?
        }
        NpmResolver::Managed(managed) => {
            resolve_managed_npm_commands(node_resolver, managed, package_env.cwd(), &python_exe)?
        }
    };
    commands.insert("deno".to_string(), Rc::new(UnsupportedDenoCommand));
    commands
        .entry("node".to_string())
        .or_insert_with(|| Rc::new(NodeCommand) as Rc<dyn ShellCommand>);
    Ok((commands, bin_dirs))
}

fn resolve_byonm_npm_commands(
    node_resolver: &EmbedNodeResolver,
    bin_dirs: &[PathBuf],
    project_cwd: &Path,
    python_exe: &Path,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let mut commands = HashMap::new();
    for bin_dir in bin_dirs {
        if !bin_dir.is_dir() {
            continue;
        }
        for (command_name, path) in node_resolver.resolve_npm_commands_from_bin_dir(bin_dir) {
            commands.entry(command_name.clone()).or_insert_with(|| {
                Rc::new(NodeModulesFileRunCommand::new(
                    command_name,
                    path.path().to_path_buf(),
                    project_cwd,
                    python_exe.to_path_buf(),
                )) as Rc<dyn ShellCommand>
            });
        }
    }
    Ok(commands)
}

fn resolve_task_node_modules_bin_dirs(
    npm_resolver: &NpmResolver<EmbedSys>,
    cwd: &Path,
) -> Vec<PathBuf> {
    match npm_resolver {
        NpmResolver::Byonm(_) => cwd
            .ancestors()
            .map(|dir| dir.join("node_modules").join(".bin"))
            .collect(),
        NpmResolver::Managed(managed) => managed
            .root_node_modules_path()
            .map(|path| vec![path.join(".bin")])
            .unwrap_or_default(),
    }
}

fn resolve_managed_npm_commands(
    node_resolver: &EmbedNodeResolver,
    npm_resolver: &ManagedNpmResolver<EmbedSys>,
    project_cwd: &Path,
    python_exe: &Path,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let mut result = HashMap::new();
    for id in npm_resolver.resolution().top_level_packages() {
        let package_folder = npm_resolver
            .resolve_pkg_folder_from_pkg_id(&id)
            .with_context(|| format!("Failed resolving npm package folder for '{id}'"))?;
        let bins = node_resolver
            .resolve_npm_binary_commands_for_package(&package_folder)
            .with_context(|| {
                format!(
                    "Failed resolving npm binary commands for '{}'",
                    package_folder.display()
                )
            })?;
        for (command_name, path) in bins {
            result.insert(
                command_name.clone(),
                Rc::new(NodeModulesFileRunCommand::new(
                    command_name,
                    path.path().to_path_buf(),
                    project_cwd,
                    python_exe.to_path_buf(),
                )) as Rc<dyn ShellCommand>,
            );
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;

    use super::*;

    #[test]
    fn task_bin_helper_args_include_private_runtime_and_forwarded_arguments() {
        let project_cwd = Path::new("/project");
        let task_cwd = Path::new("/project/app");
        let path = Path::new("/project/node_modules/vite/bin/vite.js");
        let result = task_bin_helper_args(
            project_cwd,
            task_cwd,
            "vite",
            path,
            vec!["build".into(), "--emptyOutDir".into()],
        );

        assert_eq!(
            result,
            vec![
                OsString::from("-m"),
                OsString::from("belgie._task_runtime"),
                OsString::from("npm-bin"),
                OsString::from("--project-cwd"),
                OsString::from("/project"),
                OsString::from("--cwd"),
                OsString::from("/project/app"),
                OsString::from("--command-name"),
                OsString::from("vite"),
                OsString::from("--"),
                OsString::from("/project/node_modules/vite/bin/vite.js"),
                OsString::from("build"),
                OsString::from("--emptyOutDir"),
            ]
        );
    }
}
