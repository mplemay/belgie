use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use deno_lib::worker::LibWorkerFactoryRoots;

use crate::command::CommandSource;
use crate::runtime::bound_runtime::{BoundPackageEnvironment, ImplicitPackageEnvironment};
use crate::runtime::{
    BoundRuntime, CommandExecutionHandle, CommandExecutionOptions, DenoExecutionHandle, DenoRuntime,
};
use crate::script::ScriptSource;
use crate::types::error::BindingError;

struct PendingScriptBind<'a> {
    counter: &'a AtomicUsize,
}

impl Drop for PendingScriptBind<'_> {
    fn drop(&mut self) {
        self.counter.fetch_sub(1, Ordering::AcqRel);
    }
}

pub(crate) struct RuntimeSession {
    runtime: DenoRuntime,
    package_environment: Mutex<Option<BoundPackageEnvironment>>,
    active: AtomicBool,
    scripts: Mutex<Vec<DenoExecutionHandle>>,
    commands: Mutex<Vec<CommandExecutionHandle>>,
    pending_script_binds: AtomicUsize,
    worker_factory_roots: LibWorkerFactoryRoots,
}

impl std::fmt::Debug for RuntimeSession {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("RuntimeSession")
            .field("runtime", &self.runtime)
            .field("active", &self.active.load(Ordering::Acquire))
            .field(
                "pending_script_binds",
                &self.pending_script_binds.load(Ordering::Acquire),
            )
            .finish_non_exhaustive()
    }
}

impl RuntimeSession {
    pub(crate) fn activate(runtime: DenoRuntime) -> Result<Arc<Self>, BindingError> {
        let package_environment = match BoundPackageEnvironment::from_isolated_runtime(&runtime)? {
            Some(BoundPackageEnvironment::Isolated(active))
                if active.needs_package_environment(runtime.worker_options()) =>
            {
                Some(BoundPackageEnvironment::Isolated(active))
            }
            _ => None,
        };
        Ok(Arc::new(Self {
            runtime,
            package_environment: Mutex::new(package_environment),
            active: AtomicBool::new(true),
            scripts: Mutex::new(Vec::new()),
            commands: Mutex::new(Vec::new()),
            pending_script_binds: AtomicUsize::new(0),
            worker_factory_roots: LibWorkerFactoryRoots::default(),
        }))
    }

    pub(crate) fn bind_script(
        session: &Arc<Self>,
        script: ScriptSource,
    ) -> Result<DenoExecutionHandle, BindingError> {
        session.ensure_active()?;
        let bound = session.runtime.bind(script);
        session.pending_script_binds.fetch_add(1, Ordering::AcqRel);
        let _pending_script_bind = PendingScriptBind {
            counter: &session.pending_script_binds,
        };
        let package_environment = session.package_environment_for_script(&bound)?;
        let bound = bound.with_package_environment(package_environment);
        let handle = DenoExecutionHandle::new(bound, Arc::clone(session));
        session
            .scripts
            .lock()
            .expect("runtime script handle lock should not be poisoned")
            .push(handle.clone());
        Ok(handle)
    }

    pub(crate) fn start_command(
        session: Arc<Self>,
        command: CommandSource,
        argv: Vec<String>,
    ) -> Result<CommandExecutionHandle, BindingError> {
        session.ensure_active()?;
        let package_environment = session
            .package_environment
            .lock()
            .expect("runtime package environment lock should not be poisoned")
            .clone()
            .filter(|environment| environment.supports_commands())
            .ok_or_else(|| {
                BindingError::runtime(
                    "Commands require an active Environment with package dependencies",
                )
            })?;
        let handle = CommandExecutionHandle::spawn(CommandExecutionOptions {
            package_environment,
            js_runtime_options: session.runtime.js_runtime_options().clone(),
            runtime_worker_options: session.runtime.worker_options().clone(),
            runtime_root: session.runtime.cwd().to_path_buf(),
            command,
            argv,
            session: Arc::clone(&session),
        });
        session
            .commands
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
        *self
            .package_environment
            .lock()
            .expect("runtime package environment lock should not be poisoned") = None;
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

    #[cfg(test)]
    pub(crate) fn package_environment_for_script(
        &self,
        bound: &BoundRuntime,
    ) -> Result<Option<BoundPackageEnvironment>, BindingError> {
        self.resolve_package_environment_for_script(bound)
    }

    #[cfg(not(test))]
    fn package_environment_for_script(
        &self,
        bound: &BoundRuntime,
    ) -> Result<Option<BoundPackageEnvironment>, BindingError> {
        self.resolve_package_environment_for_script(bound)
    }

    fn resolve_package_environment_for_script(
        &self,
        bound: &BoundRuntime,
    ) -> Result<Option<BoundPackageEnvironment>, BindingError> {
        let mut package_environment = self
            .package_environment
            .lock()
            .expect("runtime package environment lock should not be poisoned");

        if !bound.script().needs_package_loader() {
            return Ok(BoundPackageEnvironment::for_script_without_package_loader(
                package_environment.as_ref(),
            ));
        }

        if let Some(existing) = package_environment.clone() {
            return Ok(Some(existing));
        }

        let environment = match BoundPackageEnvironment::from_isolated_runtime(&self.runtime)? {
            Some(environment) => environment,
            None => BoundPackageEnvironment::Implicit(Arc::new(ImplicitPackageEnvironment::new(
                self.runtime.cwd(),
            )?)),
        };
        *package_environment = Some(environment.clone());
        Ok(Some(environment))
    }

    pub(crate) fn worker_factory_roots(&self) -> &LibWorkerFactoryRoots {
        &self.worker_factory_roots
    }

    pub(crate) fn cli_snapshot_eligible(&self) -> bool {
        let scripts = self
            .scripts
            .lock()
            .expect("runtime script handle lock should not be poisoned");
        scripts.is_empty() && self.pending_script_binds.load(Ordering::Acquire) == 0
    }
}

impl Drop for RuntimeSession {
    fn drop(&mut self) {
        let _ = self.close_blocking();
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::Ordering;
    use std::sync::{Arc, Barrier};
    use std::thread;

    use crate::options::{RuntimeOptions, ScriptOptions};
    use crate::runtime::DenoRuntime;
    use crate::script::ScriptSource;

    use super::RuntimeSession;

    fn test_session() -> Arc<RuntimeSession> {
        let cwd = std::env::current_dir().expect("current dir should be available");
        RuntimeSession::activate(DenoRuntime::new(RuntimeOptions::new(cwd)))
            .expect("runtime session should activate")
    }

    #[test]
    fn cli_snapshot_eligible_when_no_scripts_are_bound() {
        let session = test_session();
        assert!(session.cli_snapshot_eligible());
    }

    #[test]
    fn cli_snapshot_ineligible_while_script_bind_is_pending() {
        let session = test_session();
        let start_barrier = Arc::new(Barrier::new(2));
        let finish_barrier = Arc::new(Barrier::new(2));
        let session_for_thread = session.clone();
        let start_barrier_for_thread = start_barrier.clone();
        let finish_barrier_for_thread = finish_barrier.clone();

        let pending = thread::spawn(move || {
            session_for_thread
                .pending_script_binds
                .fetch_add(1, Ordering::AcqRel);
            start_barrier_for_thread.wait();
            finish_barrier_for_thread.wait();
            session_for_thread
                .pending_script_binds
                .fetch_sub(1, Ordering::AcqRel);
        });

        start_barrier.wait();
        assert!(!session.cli_snapshot_eligible());
        finish_barrier.wait();
        pending.join().expect("pending bind thread should finish");
        assert!(session.cli_snapshot_eligible());
    }

    #[test]
    fn cli_snapshot_ineligible_after_script_is_bound() {
        let session = test_session();
        let script = ScriptSource::from_options(ScriptOptions::inline(
            "export default function run() { return 'ok'; }".to_string(),
        ));
        RuntimeSession::bind_script(&session, script).expect("script should bind");
        assert!(!session.cli_snapshot_eligible());
    }

    #[test]
    fn reuses_implicit_package_environment_for_multiple_inline_dep_binds() {
        use crate::runtime::BoundPackageEnvironment;

        let session = test_session();
        let npm_script = ScriptSource::from_options(ScriptOptions::inline(
            r#"import isNumber from "npm:is-number@7.0.0"; export default () => isNumber(1);"#
                .to_string(),
        ));
        let jsr_script = ScriptSource::from_options(ScriptOptions::inline(
            r#"import { assertEquals } from "jsr:@std/assert@1"; export default () => 1;"#
                .to_string(),
        ));

        RuntimeSession::bind_script(&session, npm_script).expect("npm script should bind");
        let first = session
            .package_environment
            .lock()
            .expect("runtime package environment lock should not be poisoned")
            .clone()
            .expect("implicit environment should be created");

        RuntimeSession::bind_script(&session, jsr_script).expect("jsr script should bind");
        let second = session
            .package_environment
            .lock()
            .expect("runtime package environment lock should not be poisoned")
            .clone()
            .expect("implicit environment should remain");

        match (first, second) {
            (
                BoundPackageEnvironment::Implicit(first),
                BoundPackageEnvironment::Implicit(second),
            ) => assert!(Arc::ptr_eq(&first, &second)),
            other => panic!("expected implicit environments, got {other:?}"),
        }
    }

    #[test]
    fn simple_script_does_not_inherit_implicit_package_environment() {
        use crate::runtime::BoundPackageEnvironment;

        let session = test_session();
        let npm_script = ScriptSource::from_options(ScriptOptions::inline(
            r#"import isNumber from "npm:is-number@7.0.0"; export default () => isNumber(1);"#
                .to_string(),
        ));
        let simple_script = ScriptSource::from_options(ScriptOptions::inline(
            "export default () => 'ok';".to_string(),
        ));

        RuntimeSession::bind_script(&session, npm_script).expect("npm script should bind");
        assert!(matches!(
            session
                .package_environment
                .lock()
                .expect("runtime package environment lock should not be poisoned")
                .as_ref(),
            Some(BoundPackageEnvironment::Implicit(_))
        ));

        let bound = session.runtime.bind(simple_script);
        let assigned = session
            .package_environment_for_script(&bound)
            .expect("package environment should resolve");
        assert!(assigned.is_none());
    }
}
