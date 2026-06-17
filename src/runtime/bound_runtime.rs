use std::{path::Path, sync::Arc};

use crate::environment::ActiveEnvironment;
use crate::options::{JsRuntimeOptions, RuntimeEnvironment};
use crate::script::ScriptSource;

use super::DenoRuntime;

#[derive(Clone, Debug)]
pub(crate) struct BoundRuntime {
    runtime: DenoRuntime,
    script: ScriptSource,
    active_environment: Option<Arc<ActiveEnvironment>>,
}

impl BoundRuntime {
    pub(crate) fn new(runtime: DenoRuntime, script: ScriptSource) -> Self {
        Self {
            runtime,
            script,
            active_environment: None,
        }
    }

    pub(crate) fn cwd(&self) -> &Path {
        self.runtime.cwd()
    }

    pub(crate) fn js_runtime_options(&self) -> &JsRuntimeOptions {
        self.runtime.js_runtime_options()
    }

    pub(crate) fn environment(&self) -> Option<&Arc<ActiveEnvironment>> {
        self.active_environment.as_ref()
    }

    pub(crate) fn runtime_environment(&self) -> Option<&RuntimeEnvironment> {
        self.runtime.environment()
    }

    pub(crate) fn with_environment(mut self, environment: Option<Arc<ActiveEnvironment>>) -> Self {
        self.active_environment = environment;
        self
    }

    pub(crate) fn script(&self) -> &ScriptSource {
        &self.script
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
