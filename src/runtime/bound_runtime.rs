use std::{
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};

use tempfile::TempDir;

use crate::embed::{EmbedContext, EmbedContextOptions};
use crate::environment::ActiveEnvironment;
use crate::options::{JsRuntimeOptions, RuntimeEnvironment, RuntimeWorkerOptions};
use crate::script::ScriptSource;
use crate::types::error::BindingError;

use super::DenoRuntime;

#[derive(Clone, Debug)]
pub(crate) struct BoundRuntime {
    runtime: DenoRuntime,
    script: ScriptSource,
    package_environment: Option<BoundPackageEnvironment>,
}

#[derive(Clone, Debug)]
pub(crate) enum BoundPackageEnvironment {
    Isolated(Arc<ActiveEnvironment>),
    Implicit(Arc<ImplicitPackageEnvironment>),
}

pub(crate) struct ImplicitPackageEnvironment {
    workspace: PathBuf,
    lockfile: PathBuf,
    options: EmbedContextOptions,
    _temp_dir: TempDir,
}

impl std::fmt::Debug for ImplicitPackageEnvironment {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ImplicitPackageEnvironment")
            .field("workspace", &self.workspace)
            .field("lockfile", &self.lockfile)
            .finish_non_exhaustive()
    }
}

impl ImplicitPackageEnvironment {
    pub(crate) fn new(workspace: &Path) -> Result<Self, BindingError> {
        let temp_dir = tempfile::Builder::new()
            .prefix("belgie-inline-deps-")
            .tempdir()
            .map_err(|error| {
                BindingError::runtime(format!(
                    "Creating temporary inline dependency environment failed: {error}"
                ))
            })?;
        let root = deno_path_util::strip_unc_prefix(temp_dir.path().to_path_buf());
        Ok(Self {
            workspace: workspace.to_path_buf(),
            lockfile: root.join("deno.lock"),
            options: EmbedContextOptions {
                node_modules_root: Some(root.join("node_modules")),
                ..Default::default()
            },
            _temp_dir: temp_dir,
        })
    }

    fn embed_context(
        &self,
        worker_options: &RuntimeWorkerOptions,
    ) -> Result<Rc<EmbedContext>, BindingError> {
        let mut options = self.options.clone();
        options.enable_raw_imports = worker_options.enable_raw_imports();
        Ok(Rc::new(
            EmbedContext::new_with_options(self.workspace.clone(), self.lockfile.clone(), options)
                .map_err(|error| BindingError::runtime(error.to_string()))?,
        ))
    }
}

impl BoundPackageEnvironment {
    pub(crate) fn from_isolated_runtime(
        runtime: &DenoRuntime,
    ) -> Result<Option<Self>, BindingError> {
        let Some(RuntimeEnvironment::Isolated(isolated)) = runtime.environment() else {
            return Ok(None);
        };
        let active = isolated
            .acquire_active()
            .map_err(|error| BindingError::runtime(error.to_string()))?;
        Ok(Some(Self::Isolated(active)))
    }

    pub(crate) fn for_script_without_package_loader(existing: Option<&Self>) -> Option<Self> {
        match existing {
            Some(Self::Isolated(environment)) => Some(Self::Isolated(Arc::clone(environment))),
            _ => None,
        }
    }

    pub(crate) fn supports_commands(&self) -> bool {
        match self {
            Self::Isolated(environment) => environment.has_package_dependencies(),
            Self::Implicit(_) => false,
        }
    }

    pub(crate) fn embed_context_rc(
        &self,
        worker_options: &RuntimeWorkerOptions,
    ) -> Result<Rc<EmbedContext>, BindingError> {
        match self {
            Self::Isolated(environment) => environment
                .embed_context_with_worker_options(worker_options)
                .map_err(|error| BindingError::runtime(error.to_string())),
            Self::Implicit(environment) => environment.embed_context(worker_options),
        }
    }

    pub(crate) fn refresh_local_file_dependencies(&self) -> Result<(), BindingError> {
        match self {
            Self::Isolated(environment) => environment
                .refresh_local_file_dependencies(false)
                .map_err(|error| BindingError::runtime(error.to_string())),
            Self::Implicit(_) => Ok(()),
        }
    }
}

impl BoundRuntime {
    pub(crate) fn new(runtime: DenoRuntime, script: ScriptSource) -> Self {
        Self {
            runtime,
            script,
            package_environment: None,
        }
    }

    pub(crate) fn cwd(&self) -> &Path {
        self.runtime.cwd()
    }

    pub(crate) fn js_runtime_options(&self) -> &JsRuntimeOptions {
        self.runtime.js_runtime_options()
    }

    pub(crate) fn worker_options(&self) -> &RuntimeWorkerOptions {
        self.runtime.worker_options()
    }

    pub(crate) fn package_environment(&self) -> Option<&BoundPackageEnvironment> {
        self.package_environment.as_ref()
    }

    pub(crate) fn with_package_environment(
        mut self,
        environment: Option<BoundPackageEnvironment>,
    ) -> Self {
        self.package_environment = environment;
        self
    }

    pub(crate) fn script(&self) -> &ScriptSource {
        &self.script
    }

    pub(crate) fn run_signature(&self) -> Option<&crate::script::RunSignature> {
        self.script.run_signature()
    }

    pub(crate) fn description(&self) -> String {
        format!(
            "{} bound in {}",
            self.script().description(),
            self.cwd().display()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::BoundRuntime;
    use crate::{
        options::{RuntimeOptions, ScriptOptions},
        runtime::DenoRuntime,
        script::ScriptSource,
    };
    use std::path::PathBuf;

    #[test]
    fn exposes_bound_runtime_context() {
        let cwd = PathBuf::from("/tmp/belgie/project");
        let runtime = DenoRuntime::new(RuntimeOptions::new(cwd.clone()));
        let script = ScriptSource::from_options(ScriptOptions::from_file(
            "export default () => 42;".to_string(),
            PathBuf::from("/tmp/belgie/project/main.ts"),
        ));

        let bound = BoundRuntime::new(runtime, script);

        assert_eq!(bound.cwd(), cwd.as_path());
        assert_eq!(bound.script().content(), "export default () => 42;");
        assert_eq!(
            bound.description(),
            "file script at /tmp/belgie/project/main.ts bound in /tmp/belgie/project"
        );
    }
}
