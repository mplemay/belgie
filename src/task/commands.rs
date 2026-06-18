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

const TASK_RUNTIME_MODULE: &str = "belgie._task_runtime";

#[derive(Clone)]
struct NodeModulesFileRunCommand {
    command_name: String,
    path: PathBuf,
    project_dir: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    python_path: PathBuf,
    executable_name: String,
}

impl ShellCommand for NodeModulesFileRunCommand {
    fn execute(&self, context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let args = task_runtime_args(
            &self.project_dir,
            &self.config_file,
            &self.lockfile,
            &self.command_name,
            &self.path,
            context.args,
        );
        ExecutableCommand::new(self.executable_name.clone(), self.python_path.clone())
            .execute(ShellCommandContext { args, ..context })
    }
}

impl NodeModulesFileRunCommand {
    fn new(
        command_name: String,
        path: PathBuf,
        project_dir: &Path,
        config_file: &Path,
        lockfile: &Path,
        python_path: &Path,
    ) -> Self {
        let executable_name = python_path
            .file_stem()
            .and_then(|name| name.to_str())
            .unwrap_or("python")
            .to_string();
        Self {
            command_name,
            path,
            project_dir: project_dir.to_path_buf(),
            config_file: config_file.to_path_buf(),
            lockfile: lockfile.to_path_buf(),
            python_path: python_path.to_path_buf(),
            executable_name,
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

fn task_runtime_args(
    project_dir: &Path,
    config_file: &Path,
    lockfile: &Path,
    command_name: &str,
    path: &Path,
    args: Vec<OsString>,
) -> Vec<OsString> {
    let mut result = vec![
        OsString::from("-m"),
        OsString::from(TASK_RUNTIME_MODULE),
        project_dir.as_os_str().to_os_string(),
        config_file.as_os_str().to_os_string(),
        lockfile.as_os_str().to_os_string(),
        OsString::from(command_name),
        path.as_os_str().to_os_string(),
    ];
    result.extend(args);
    result
}

fn npm_bin_shell_command(
    command_name: String,
    path: PathBuf,
    project_dir: &Path,
    config_file: &Path,
    lockfile: &Path,
    python_path: &Path,
) -> Rc<dyn ShellCommand> {
    Rc::new(NodeModulesFileRunCommand::new(
        command_name,
        path,
        project_dir,
        config_file,
        lockfile,
        python_path,
    ))
}

pub(crate) async fn prepare_custom_commands(
    package_env: &PackageEnvironment,
    cwd: &Path,
    python_path: &Path,
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
    let project_dir = package_env.cwd();
    let config_file = package_env.config_file();
    let lockfile = package_env.lockfile();

    let mut commands = match npm_resolver {
        NpmResolver::Byonm(_) => resolve_byonm_npm_commands(
            node_resolver,
            &bin_dirs,
            project_dir,
            config_file,
            lockfile,
            python_path,
        ),
        NpmResolver::Managed(managed) => resolve_managed_npm_commands(
            node_resolver,
            managed,
            project_dir,
            config_file,
            lockfile,
            python_path,
        )?,
    };
    commands.insert("deno".to_string(), Rc::new(UnsupportedDenoCommand));
    Ok((commands, bin_dirs))
}

fn resolve_byonm_npm_commands(
    node_resolver: &EmbedNodeResolver,
    bin_dirs: &[PathBuf],
    project_dir: &Path,
    config_file: &Path,
    lockfile: &Path,
    python_path: &Path,
) -> HashMap<String, Rc<dyn ShellCommand>> {
    let mut commands = HashMap::new();
    for bin_dir in bin_dirs {
        if !bin_dir.is_dir() {
            continue;
        }
        for (command_name, path) in node_resolver.resolve_npm_commands_from_bin_dir(bin_dir) {
            commands.entry(command_name.clone()).or_insert_with(|| {
                npm_bin_shell_command(
                    command_name,
                    path.path().to_path_buf(),
                    project_dir,
                    config_file,
                    lockfile,
                    python_path,
                )
            });
        }
    }
    commands
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
    project_dir: &Path,
    config_file: &Path,
    lockfile: &Path,
    python_path: &Path,
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
                npm_bin_shell_command(
                    command_name,
                    path.path().to_path_buf(),
                    project_dir,
                    config_file,
                    lockfile,
                    python_path,
                ),
            );
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn npm_bin_command_preserves_virtualenv_python_path() {
        let python_path = PathBuf::from("/project/.venv/bin/python");
        let command = NodeModulesFileRunCommand::new(
            "vite".to_string(),
            PathBuf::from("/project/node_modules/vite/bin/vite.js"),
            Path::new("/project"),
            Path::new("/project/deno.json"),
            Path::new("/project/deno.lock"),
            &python_path,
        );

        assert_eq!(command.python_path, python_path);
        assert_eq!(command.executable_name, "python");
    }

    #[test]
    fn task_runtime_args_include_private_module_and_forwarded_arguments() {
        let result = task_runtime_args(
            Path::new("/project"),
            Path::new("/project/deno.json"),
            Path::new("/project/deno.lock"),
            "vite",
            Path::new("/project/node_modules/vite/bin/vite.js"),
            vec!["build".into(), "--emptyOutDir".into()],
        );

        assert_eq!(
            result,
            vec![
                OsString::from("-m"),
                OsString::from("belgie._task_runtime"),
                OsString::from("/project"),
                OsString::from("/project/deno.json"),
                OsString::from("/project/deno.lock"),
                OsString::from("vite"),
                OsString::from("/project/node_modules/vite/bin/vite.js"),
                OsString::from("build"),
                OsString::from("--emptyOutDir"),
            ]
        );
    }
}
