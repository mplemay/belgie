use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use crate::command::CommandSource;
use crate::runtime::{
    BoundPackageEnvironment, CommandExecutionHandle, CommandExecutionOptions, DenoExecutionHandle,
    DenoRuntime,
};
use crate::script::ScriptSource;
use crate::types::error::BindingError;

#[derive(Debug)]
pub(crate) struct RuntimeSession {
    runtime: DenoRuntime,
    package_environment: Option<BoundPackageEnvironment>,
    active: AtomicBool,
    scripts: Mutex<Vec<DenoExecutionHandle>>,
    commands: Mutex<Vec<CommandExecutionHandle>>,
}

impl RuntimeSession {
    pub(crate) fn activate(runtime: DenoRuntime) -> Result<Arc<Self>, BindingError> {
        let package_environment = match runtime.environment() {
            Some(environment) => {
                if let Some(isolated) = environment.isolated() {
                    let active = isolated
                        .acquire_active()
                        .map_err(|error| BindingError::runtime(error.to_string()))?;
                    active
                        .uses_package_loader()
                        .then_some(BoundPackageEnvironment::Isolated(active))
                } else {
                    None
                }
            }
            None => None,
        };
        Ok(Arc::new(Self {
            runtime,
            package_environment,
            active: AtomicBool::new(true),
            scripts: Mutex::new(Vec::new()),
            commands: Mutex::new(Vec::new()),
        }))
    }

    pub(crate) fn bind_script(
        &self,
        script: ScriptSource,
    ) -> Result<DenoExecutionHandle, BindingError> {
        self.ensure_active()?;
        let bound = self
            .runtime
            .bind(script)
            .with_package_environment(self.package_environment.clone());
        let handle = DenoExecutionHandle::new(bound);
        self.scripts
            .lock()
            .expect("runtime script handle lock should not be poisoned")
            .push(handle.clone());
        Ok(handle)
    }

    pub(crate) fn start_command(
        &self,
        command: CommandSource,
        argv: Vec<String>,
    ) -> Result<CommandExecutionHandle, BindingError> {
        self.ensure_active()?;
        let package_environment = self.package_environment.clone().ok_or_else(|| {
            BindingError::runtime(
                "Commands require an active Environment with package dependencies",
            )
        })?;
        let handle = CommandExecutionHandle::spawn(CommandExecutionOptions {
            package_environment,
            runtime_root: self.runtime.cwd().to_path_buf(),
            command,
            argv,
        });
        self.commands
            .lock()
            .expect("runtime command handle lock should not be poisoned")
            .push(handle.clone());
        Ok(handle)
    }

    pub(crate) fn close_blocking(&self) -> Result<(), BindingError> {
        if !self.active.swap(false, Ordering::AcqRel) {
            return Ok(());
        }

        let commands = std::mem::take(
            &mut *self
                .commands
                .lock()
                .expect("runtime command handle lock should not be poisoned"),
        );
        for command in &commands {
            command.cancel();
        }

        let scripts = std::mem::take(
            &mut *self
                .scripts
                .lock()
                .expect("runtime script handle lock should not be poisoned"),
        );
        for script in &scripts {
            script.cancel();
        }

        for command in commands {
            command.close_blocking()?;
        }
        for script in scripts {
            script.close_blocking()?;
        }
        Ok(())
    }

    pub(crate) fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    pub(crate) fn description(&self) -> String {
        format!("runtime session in {}", self.runtime.cwd().display())
    }

    fn ensure_active(&self) -> Result<(), BindingError> {
        if self.is_active() {
            Ok(())
        } else {
            Err(BindingError::runtime("Runtime session is closed"))
        }
    }
}

impl Drop for RuntimeSession {
    fn drop(&mut self) {
        let _ = self.close_blocking();
    }
}
