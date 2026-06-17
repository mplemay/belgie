use std::collections::HashMap;
use std::ffi::{OsStr, OsString};
use std::fs;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use deno_config::deno_json::NodeModulesLinkerMode;
use deno_core::anyhow::Context;
use deno_core::error::AnyError;
use deno_core::futures::future::LocalBoxFuture;
use deno_npm_installer::process_state::{
    NpmProcessState, NpmProcessStateKind, NpmProcessStateLinkerMode,
};
use deno_resolver::npm::ManagedNpmResolver;
use deno_resolver::npm::NpmResolver;
use deno_runtime::deno_process::NPM_RESOLUTION_STATE_FD_ENV_VAR_NAME;
use deno_task_shell::ExecutableCommand;
use deno_task_shell::ExecuteResult;
use deno_task_shell::ShellCommand;
use deno_task_shell::ShellCommandContext;
use node_resolver::DenoIsBuiltInNodeModuleChecker;
use node_resolver::NodeResolver;

use crate::embed::sys::EmbedSys;
use crate::packages::{PackageEnvironment, project_state_error};
use crate::task::deno_exe::resolve_deno_exe;

type EmbedNodeResolver = NodeResolver<
    deno_resolver::npm::DenoInNpmPackageChecker,
    DenoIsBuiltInNodeModuleChecker,
    NpmResolver<EmbedSys>,
    EmbedSys,
>;

const RUN_SUBCOMMAND: &str = "run";

fn first_subcommand_index(args: &[OsString]) -> Option<usize> {
    args.iter()
        .position(|arg| arg.to_str().is_none_or(|value| !value.starts_with('-')))
}

#[derive(Clone)]
struct BelgieDenoCommand {
    deno_path: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    process_state_file: PathBuf,
}

impl BelgieDenoCommand {
    fn new(
        package_env: &PackageEnvironment,
        npm_resolver: &NpmResolver<EmbedSys>,
    ) -> Result<Self, AnyError> {
        let process_state_file = write_process_state(package_env, npm_resolver)?;
        Ok(Self {
            deno_path: resolve_deno_exe()?,
            config_file: package_env.config_file().to_path_buf(),
            lockfile: package_env.lockfile().to_path_buf(),
            process_state_file,
        })
    }

    fn with_config_args(&self, args: Vec<OsString>) -> Vec<OsString> {
        let config_args = [
            OsString::from("--config"),
            self.config_file.as_os_str().to_os_string(),
            OsString::from("--lock"),
            self.lockfile.as_os_str().to_os_string(),
        ];
        let insert_at = first_subcommand_index(&args)
            .filter(|&index| args[index] == RUN_SUBCOMMAND)
            .map(|index| index + 1)
            .unwrap_or(0);

        let mut result = Vec::with_capacity(args.len() + config_args.len());
        result.extend(args.iter().take(insert_at).cloned());
        result.extend(config_args);
        result.extend(args.into_iter().skip(insert_at));
        result
    }
}

impl ShellCommand for BelgieDenoCommand {
    fn execute(&self, mut context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let deno_path = self.deno_path.clone();
        let args = self.with_config_args(context.args);
        context.state.apply_env_var(
            OsStr::new(NPM_RESOLUTION_STATE_FD_ENV_VAR_NAME),
            self.process_state_file.as_os_str(),
        );
        ExecutableCommand::new("deno".to_string(), deno_path)
            .execute(ShellCommandContext { args, ..context })
    }
}

struct BelgieDenoShellCommand(Rc<BelgieDenoCommand>);

impl ShellCommand for BelgieDenoShellCommand {
    fn execute(&self, context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        self.0.as_ref().execute(context)
    }
}

#[derive(Clone)]
struct NodeModulesFileRunCommand {
    command_name: String,
    path: PathBuf,
    deno_command: Rc<BelgieDenoCommand>,
}

impl ShellCommand for NodeModulesFileRunCommand {
    fn execute(&self, mut context: ShellCommandContext) -> LocalBoxFuture<'static, ExecuteResult> {
        let mut args: Vec<OsString> = vec![
            RUN_SUBCOMMAND.into(),
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
            .as_ref()
            .execute(ShellCommandContext { args, ..context })
    }
}

fn npm_bin_shell_command(
    command_name: String,
    path: PathBuf,
    deno_command: Rc<BelgieDenoCommand>,
) -> Rc<dyn ShellCommand> {
    Rc::new(NodeModulesFileRunCommand {
        command_name,
        path,
        deno_command,
    })
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
    let resolved_deno = BelgieDenoCommand::new(package_env, npm_resolver).map(Rc::new);

    let mut commands = match npm_resolver {
        NpmResolver::Byonm(_) => {
            resolve_byonm_npm_commands(node_resolver, &bin_dirs, &resolved_deno)?
        }
        NpmResolver::Managed(managed) => {
            resolve_managed_npm_commands(node_resolver, managed, &resolved_deno)?
        }
    };

    if let Ok(deno_command) = &resolved_deno {
        commands.insert(
            "deno".to_string(),
            Rc::new(BelgieDenoShellCommand(Rc::clone(deno_command))),
        );
    }
    Ok((commands, bin_dirs))
}

fn write_process_state(
    package_env: &PackageEnvironment,
    npm_resolver: &NpmResolver<EmbedSys>,
) -> Result<PathBuf, AnyError> {
    let state = match npm_resolver {
        NpmResolver::Managed(managed) => NpmProcessState::new_managed(
            managed.resolution().serialized_valid_snapshot(),
            managed.root_node_modules_path(),
            match managed.linker_mode() {
                NodeModulesLinkerMode::Isolated => NpmProcessStateLinkerMode::Isolated,
                NodeModulesLinkerMode::Hoisted => NpmProcessStateLinkerMode::Hoisted,
            },
        ),
        NpmResolver::Byonm(byonm) => NpmProcessState {
            kind: NpmProcessStateKind::Byonm,
            local_node_modules_path: byonm
                .root_node_modules_path()
                .map(|path| path.to_string_lossy().into_owned()),
            linker_mode: NpmProcessStateLinkerMode::default(),
        },
    };
    let path = package_env.process_state_file();
    fs::write(&path, state.as_serialized())
        .with_context(|| format!("Writing {}", path.display()))?;
    Ok(path)
}

fn resolve_byonm_npm_commands(
    node_resolver: &EmbedNodeResolver,
    bin_dirs: &[PathBuf],
    resolved_deno: &Result<Rc<BelgieDenoCommand>, AnyError>,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let mut commands = HashMap::new();
    let mut deno_command: Option<Rc<BelgieDenoCommand>> = None;
    for bin_dir in bin_dirs {
        if !bin_dir.is_dir() {
            continue;
        }
        let bins = node_resolver.resolve_npm_commands_from_bin_dir(bin_dir);
        if bins.is_empty() {
            continue;
        }
        let deno_command = match &deno_command {
            Some(command) => Rc::clone(command),
            None => {
                let command = require_deno_command(resolved_deno)?;
                deno_command = Some(Rc::clone(&command));
                command
            }
        };
        for (command_name, path) in bins {
            commands
                .entry(command_name.clone())
                .or_insert(npm_bin_shell_command(
                    command_name,
                    path.path().to_path_buf(),
                    Rc::clone(&deno_command),
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
    resolved_deno: &Result<Rc<BelgieDenoCommand>, AnyError>,
) -> Result<Rc<BelgieDenoCommand>, AnyError> {
    match resolved_deno {
        Ok(deno_command) => Ok(Rc::clone(deno_command)),
        Err(error) => Err(deno_core::anyhow::anyhow!("{error}")),
    }
}

fn resolve_managed_npm_commands(
    node_resolver: &EmbedNodeResolver,
    npm_resolver: &ManagedNpmResolver<EmbedSys>,
    resolved_deno: &Result<Rc<BelgieDenoCommand>, AnyError>,
) -> Result<HashMap<String, Rc<dyn ShellCommand>>, AnyError> {
    let packages = npm_resolver.resolution().top_level_packages();
    if packages.is_empty() {
        return Ok(HashMap::new());
    }
    let deno_command = require_deno_command(resolved_deno)?;
    let mut result = HashMap::new();
    for id in packages {
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
                    Rc::clone(&deno_command),
                ),
            );
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_deno_command() -> BelgieDenoCommand {
        BelgieDenoCommand {
            deno_path: PathBuf::from("/deno"),
            config_file: PathBuf::from("/embed/deno.json"),
            lockfile: PathBuf::from("/embed/deno.lock"),
            process_state_file: PathBuf::from("/embed/npm-process-state.json"),
        }
    }

    #[test]
    fn with_config_args_inserts_after_run() {
        let command = sample_deno_command();
        let result = command.with_config_args(vec![
            "run".into(),
            "--ext=js".into(),
            "-A".into(),
            "script.js".into(),
        ]);
        assert_eq!(
            result,
            vec![
                OsString::from("run"),
                OsString::from("--config"),
                OsString::from("/embed/deno.json"),
                OsString::from("--lock"),
                OsString::from("/embed/deno.lock"),
                OsString::from("--ext=js"),
                OsString::from("-A"),
                OsString::from("script.js"),
            ]
        );
    }

    #[test]
    fn with_config_args_prepends_for_non_run_commands() {
        let command = sample_deno_command();
        let result = command.with_config_args(vec!["--version".into()]);
        assert_eq!(
            result,
            vec![
                OsString::from("--config"),
                OsString::from("/embed/deno.json"),
                OsString::from("--lock"),
                OsString::from("/embed/deno.lock"),
                OsString::from("--version"),
            ]
        );
    }

    #[test]
    fn with_config_args_inserts_after_run_with_global_flags() {
        let command = sample_deno_command();
        let result = command.with_config_args(vec![
            "--log-level=debug".into(),
            "run".into(),
            "main.ts".into(),
        ]);
        assert_eq!(
            result,
            vec![
                OsString::from("--log-level=debug"),
                OsString::from("run"),
                OsString::from("--config"),
                OsString::from("/embed/deno.json"),
                OsString::from("--lock"),
                OsString::from("/embed/deno.lock"),
                OsString::from("main.ts"),
            ]
        );
    }

    #[test]
    fn with_config_args_prepends_for_task_run() {
        let command = sample_deno_command();
        let result = command.with_config_args(vec!["task".into(), "run".into()]);
        assert_eq!(
            result,
            vec![
                OsString::from("--config"),
                OsString::from("/embed/deno.json"),
                OsString::from("--lock"),
                OsString::from("/embed/deno.lock"),
                OsString::from("task"),
                OsString::from("run"),
            ]
        );
    }

    #[test]
    fn with_config_args_prepends_for_install_run() {
        let command = sample_deno_command();
        let result = command.with_config_args(vec!["install".into(), "run".into()]);
        assert_eq!(
            result,
            vec![
                OsString::from("--config"),
                OsString::from("/embed/deno.json"),
                OsString::from("--lock"),
                OsString::from("/embed/deno.lock"),
                OsString::from("install"),
                OsString::from("run"),
            ]
        );
    }

    #[test]
    fn with_config_args_prepends_for_task_run_with_global_flags() {
        let command = sample_deno_command();
        let result = command.with_config_args(vec![
            "--log-level=debug".into(),
            "task".into(),
            "run".into(),
        ]);
        assert_eq!(
            result,
            vec![
                OsString::from("--config"),
                OsString::from("/embed/deno.json"),
                OsString::from("--lock"),
                OsString::from("/embed/deno.lock"),
                OsString::from("--log-level=debug"),
                OsString::from("task"),
                OsString::from("run"),
            ]
        );
    }
}
