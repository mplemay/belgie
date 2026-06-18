use std::collections::HashMap;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use deno_core::anyhow::{Context, anyhow};
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
use crate::task::node_exe::resolve_node_exe;

type EmbedNodeResolver = NodeResolver<
    deno_resolver::npm::DenoInNpmPackageChecker,
    DenoIsBuiltInNodeModuleChecker,
    NpmResolver<EmbedSys>,
    EmbedSys,
>;

#[derive(Clone)]
struct NodeModulesFileRunCommand {
    path: PathBuf,
    node_path: PathBuf,
}

impl ShellCommand for NodeModulesFileRunCommand {
    fn execute(&self, context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let args = node_command_args(&self.path, context.args);
        ExecutableCommand::new("node".to_string(), self.node_path.clone())
            .execute(ShellCommandContext { args, ..context })
    }
}

impl NodeModulesFileRunCommand {
    fn new(path: PathBuf, node_path: &Path) -> Self {
        Self {
            path,
            node_path: node_path.to_path_buf(),
        }
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

fn node_command_args(path: &Path, args: Vec<OsString>) -> Vec<OsString> {
    let mut result = vec![path.as_os_str().to_os_string()];
    result.extend(args);
    result
}

fn npm_bin_shell_command(path: PathBuf, node_path: &Path) -> Rc<dyn ShellCommand> {
    Rc::new(NodeModulesFileRunCommand::new(path, node_path))
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
    let resolved_node = resolve_node_exe();

    let mut commands = match npm_resolver {
        NpmResolver::Byonm(_) => {
            resolve_byonm_npm_commands(node_resolver, &bin_dirs, &resolved_node)?
        }
        NpmResolver::Managed(managed) => {
            resolve_managed_npm_commands(node_resolver, managed, &resolved_node)?
        }
    };
    commands.insert("deno".to_string(), Rc::new(UnsupportedDenoCommand));
    Ok((commands, bin_dirs))
}

fn resolve_byonm_npm_commands(
    node_resolver: &EmbedNodeResolver,
    bin_dirs: &[PathBuf],
    resolved_node: &Result<PathBuf, AnyError>,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let mut commands = HashMap::new();
    let mut node_path: Option<PathBuf> = None;
    for bin_dir in bin_dirs {
        if !bin_dir.is_dir() {
            continue;
        }
        for (command_name, path) in node_resolver.resolve_npm_commands_from_bin_dir(bin_dir) {
            if node_path.is_none() {
                node_path = Some(require_node_path(resolved_node)?);
            }
            let node_path = node_path
                .as_ref()
                .expect("node path should be resolved before command insertion");
            commands
                .entry(command_name.clone())
                .or_insert_with(|| npm_bin_shell_command(path.path().to_path_buf(), node_path));
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
    resolved_node: &Result<PathBuf, AnyError>,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let mut result = HashMap::new();
    let mut node_path: Option<PathBuf> = None;
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
            if node_path.is_none() {
                node_path = Some(require_node_path(resolved_node)?);
            }
            let node_path = node_path
                .as_ref()
                .expect("node path should be resolved before command insertion");
            result.insert(
                command_name.clone(),
                npm_bin_shell_command(path.path().to_path_buf(), node_path),
            );
        }
    }
    Ok(result)
}

fn require_node_path(resolved_node: &Result<PathBuf, AnyError>) -> Result<PathBuf, AnyError> {
    match resolved_node {
        Ok(path) => Ok(path.clone()),
        Err(error) => Err(anyhow!("{error}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn npm_bin_command_preserves_node_path() {
        let node_path = PathBuf::from("/usr/bin/node");
        let command = NodeModulesFileRunCommand::new(
            PathBuf::from("/project/node_modules/vite/bin/vite.js"),
            &node_path,
        );

        assert_eq!(command.node_path, node_path);
    }

    #[test]
    fn node_command_args_include_binary_path_and_forwarded_arguments() {
        let result = node_command_args(
            Path::new("/project/node_modules/vite/bin/vite.js"),
            vec!["build".into(), "--emptyOutDir".into()],
        );

        assert_eq!(
            result,
            vec![
                OsString::from("/project/node_modules/vite/bin/vite.js"),
                OsString::from("build"),
                OsString::from("--emptyOutDir"),
            ]
        );
    }
}
