use std::collections::HashMap;
use std::ffi::OsStr;
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
use crate::task::{TaskNpmBinOptions, run_task_npm_bin};

type EmbedNodeResolver = NodeResolver<
    deno_resolver::npm::DenoInNpmPackageChecker,
    DenoIsBuiltInNodeModuleChecker,
    NpmResolver<EmbedSys>,
    EmbedSys,
>;

const NPM_COMMAND_NAME_ENV_VAR: &str = "DENO_INTERNAL_NPM_CMD_NAME";

#[derive(Clone)]
struct NodeModulesFileRunCommand {
    command_name: String,
    project_cwd: PathBuf,
    path: PathBuf,
}

impl ShellCommand for NodeModulesFileRunCommand {
    fn execute(&self, mut context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        if let Some(exit_code) = context.state.kill_signal().aborted_code() {
            return Box::pin(std::future::ready(ExecuteResult::from_exit_code(exit_code)));
        }
        let argv = match context
            .args
            .into_iter()
            .map(|arg| {
                arg.into_string().map_err(|arg| {
                    format!(
                        "npm binary arguments must be valid Unicode: {}",
                        arg.to_string_lossy()
                    )
                })
            })
            .collect::<Result<Vec<_>, _>>()
        {
            Ok(argv) => argv,
            Err(error) => {
                let _ = context.stderr.write_line(&error);
                return Box::pin(std::future::ready(ExecuteResult::from_exit_code(1)));
            }
        };
        context.state.apply_env_var(
            OsStr::new(NPM_COMMAND_NAME_ENV_VAR),
            OsStr::new(&self.command_name),
        );
        let kill_signal = context.state.kill_signal().clone();
        let options = TaskNpmBinOptions {
            project_cwd: self.project_cwd.clone(),
            task_cwd: context.state.cwd().clone(),
            command_name: self.command_name.clone(),
            script_path: self.path.clone(),
            argv,
            env_vars: context.state.env_vars().clone(),
            stdout: context.stdout,
            stderr: context.stderr,
        };
        Box::pin(async move {
            tokio::select! {
                exit_code = run_task_npm_bin(options) => ExecuteResult::from_exit_code(exit_code),
                signal = kill_signal.wait_aborted() => ExecuteResult::from_exit_code(signal.aborted_code()),
            }
        })
    }
}

impl NodeModulesFileRunCommand {
    fn new(command_name: String, path: PathBuf, project_cwd: &Path) -> Self {
        Self {
            command_name,
            project_cwd: project_cwd.to_path_buf(),
            path,
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

    let mut commands = match npm_resolver {
        NpmResolver::Byonm(_) => {
            resolve_byonm_npm_commands(node_resolver, &bin_dirs, package_env.cwd())?
        }
        NpmResolver::Managed(managed) => {
            resolve_managed_npm_commands(node_resolver, managed, package_env.cwd())?
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
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let mut commands = HashMap::new();
    for bin_dir in bin_dirs {
        if !bin_dir.is_dir() {
            continue;
        }
        for (command_name, path) in node_resolver.resolve_npm_commands_from_bin_dir(bin_dir) {
            if !commands.contains_key(&command_name) {
                commands.insert(
                    command_name.clone(),
                    Rc::new(NodeModulesFileRunCommand::new(
                        command_name,
                        path.path().to_path_buf(),
                        project_cwd,
                    )) as Rc<dyn ShellCommand>,
                );
            }
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
        if bins.is_empty() {
            continue;
        }
        for (command_name, path) in bins {
            result.insert(
                command_name.clone(),
                Rc::new(NodeModulesFileRunCommand::new(
                    command_name,
                    path.path().to_path_buf(),
                    project_cwd,
                )) as Rc<dyn ShellCommand>,
            );
        }
    }
    Ok(result)
}
