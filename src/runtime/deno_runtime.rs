use std::path::Path;

use crate::{
    options::{JsRuntimeOptions, RuntimeEnvironment, RuntimeOptions},
    script::ScriptSource,
};

use super::BoundRuntime;

#[derive(Clone, Debug)]
pub(crate) struct DenoRuntime {
    options: RuntimeOptions,
}

impl DenoRuntime {
    pub(crate) fn new(options: RuntimeOptions) -> Self {
        Self { options }
    }

    pub(crate) fn cwd(&self) -> &Path {
        self.options.cwd()
    }

    pub(crate) fn js_runtime_options(&self) -> &JsRuntimeOptions {
        self.options.js_runtime()
    }

    pub(crate) fn environment(&self) -> Option<&RuntimeEnvironment> {
        self.options.environment()
    }

    pub(crate) fn bind(&self, script: ScriptSource) -> BoundRuntime {
        BoundRuntime::new(self.clone(), script)
    }
}

#[cfg(test)]
mod tests {
    use super::DenoRuntime;
    use crate::{
        options::{RuntimeOptions, ScriptOptions},
        script::ScriptSource,
    };
    use std::path::PathBuf;

    #[test]
    fn exposes_the_configured_working_directory() {
        let cwd = PathBuf::from("/tmp/belgie/project");
        let runtime = DenoRuntime::new(RuntimeOptions::new(cwd.clone()));

        assert_eq!(runtime.cwd(), cwd.as_path());
    }

    #[test]
    fn binding_a_script_preserves_runtime_and_script_context() {
        let cwd = PathBuf::from("/tmp/belgie/project");
        let runtime = DenoRuntime::new(RuntimeOptions::new(cwd.clone()));
        let script = ScriptSource::from_options(ScriptOptions::inline(
            "export default () => 42;".to_string(),
        ));

        let bound = runtime.bind(script);

        assert_eq!(bound.cwd(), cwd.as_path());
        assert_eq!(bound.script().content(), "export default () => 42;");
        assert!(bound.description().contains("inline script"));
        assert!(bound.description().contains("/tmp/belgie/project"));
    }
}
