use std::collections::HashMap;
use std::ffi::{OsStr, OsString};
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
use crate::packages::PackageEnvironment;
use crate::task::deno_exe::resolve_deno_exe;

type EmbedNodeResolver = NodeResolver<
    deno_resolver::npm::DenoInNpmPackageChecker,
    DenoIsBuiltInNodeModuleChecker,
    NpmResolver<EmbedSys>,
    EmbedSys,
>;

#[derive(Clone)]
struct BelgieDenoCommand {
    deno_path: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
}

impl BelgieDenoCommand {
    fn new(package_env: &PackageEnvironment) -> Result<Self, AnyError> {
        let (_, config_file, lockfile) = package_env.embed_paths();
        Ok(Self {
            deno_path: resolve_deno_exe()?,
            config_file,
            lockfile,
        })
    }

    fn prepend_config_args(&self, args: Vec<OsString>) -> Vec<OsString> {
        let mut prefixed = vec![
            OsString::from("--config"),
            self.config_file.as_os_str().to_os_string(),
            OsString::from("--lock"),
            self.lockfile.as_os_str().to_os_string(),
        ];
        prefixed.extend(args);
        prefixed
    }
}

impl ShellCommand for BelgieDenoCommand {
    fn execute(&self, context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let deno_path = self.deno_path.clone();
        let args = self.prepend_config_args(context.args);
        ExecutableCommand::new("deno".to_string(), deno_path)
            .execute(ShellCommandContext { args, ..context })
    }
}

#[derive(Clone)]
struct NodeModulesFileRunCommand {
    command_name: String,
    path: PathBuf,
    deno_command: BelgieDenoCommand,
}

impl ShellCommand for NodeModulesFileRunCommand {
    fn execute(&self, mut context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let mut args: Vec<OsString> = vec![
            "run".into(),
            "--ext=js".into(),
            "-A".into(),
            self.path.clone().into_os_string(),
        ];
        args.extend(context.args);
        context.state.apply_env_var(
            OsStr::new("DENO_INTERNAL_NPM_CMD_NAME"),
            OsStr::new(&self.command_name),
        );
        self.deno_command
            .execute(ShellCommandContext { args, ..context })
    }
}

fn npm_bin_command(
    command_name: String,
    path: PathBuf,
    deno_command: &BelgieDenoCommand,
) -> Rc<dyn ShellCommand> {
    Rc::new(NodeModulesFileRunCommand {
        command_name,
        path,
        deno_command: deno_command.clone(),
    })
}

pub(crate) async fn prepare_custom_commands(
    package_env: &PackageEnvironment,
    cwd: &Path,
) -> Result<(HashMap<String, Rc<dyn ShellCommand>>, Vec<PathBuf>), AnyError> {
    let context = package_env.embed_context()?;
    context
        .npm_installer_factory()
        .initialize_npm_resolution_if_managed()
        .await?;

    let node_resolver = context.resolver_factory().node_resolver()?;
    let npm_resolver = context.resolver_factory().npm_resolver()?;
    let bin_dirs = resolve_task_node_modules_bin_dirs(npm_resolver, cwd);
    let resolved_deno = BelgieDenoCommand::new(package_env);

    let mut commands = match npm_resolver {
        NpmResolver::Byonm(_) => {
            resolve_byonm_npm_commands(node_resolver, &bin_dirs, &resolved_deno)?
        }
        NpmResolver::Managed(managed) => {
            resolve_managed_npm_commands(node_resolver, managed, &resolved_deno)?
        }
    };

    if let Ok(deno_command) = resolved_deno {
        commands.insert("deno".to_string(), Rc::new(deno_command));
    }
    Ok((commands, bin_dirs))
}

fn resolve_byonm_npm_commands(
    node_resolver: &EmbedNodeResolver,
    bin_dirs: &[PathBuf],
    resolved_deno: &Result<BelgieDenoCommand, AnyError>,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let mut commands = HashMap::new();
    for bin_dir in bin_dirs {
        let bins = node_resolver.resolve_npm_commands_from_bin_dir(bin_dir);
        if bins.is_empty() {
            continue;
        }
        let deno_command = require_deno_command(resolved_deno)?;
        for (command_name, path) in bins {
            commands
                .entry(command_name.clone())
                .or_insert(npm_bin_command(
                    command_name,
                    path.path().to_path_buf(),
                    deno_command,
                ));
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

fn require_deno_command(
    resolved_deno: &Result<BelgieDenoCommand, AnyError>,
) -> Result<&BelgieDenoCommand, AnyError> {
    match resolved_deno {
        Ok(deno_command) => Ok(deno_command),
        Err(error) => Err(anyhow!("{error}")),
    }
}

fn resolve_managed_npm_commands(
    node_resolver: &EmbedNodeResolver,
    npm_resolver: &ManagedNpmResolver<EmbedSys>,
    resolved_deno: &Result<BelgieDenoCommand, AnyError>,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    if npm_resolver.resolution().top_level_packages().is_empty() {
        return Ok(HashMap::new());
    }
    let deno_command = require_deno_command(resolved_deno)?;
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
                npm_bin_command(command_name, path.path().to_path_buf(), deno_command),
            );
        }
    }
    Ok(result)
}
