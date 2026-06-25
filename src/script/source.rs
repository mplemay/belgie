use std::path::{Path, PathBuf};

use crate::options::ScriptOptions;
use crate::script::{ScriptDependencies, analyze_script_dependencies, media_type_for_script};

#[derive(Clone, Debug)]
pub(crate) struct ScriptSource {
    content: String,
    kind: ScriptSourceKind,
    dependencies: ScriptDependencies,
}

#[derive(Clone, Debug)]
enum ScriptSourceKind {
    Inline,
    File { path: PathBuf },
}

impl ScriptSource {
    pub(crate) fn from_options(options: ScriptOptions) -> Self {
        let path = options.path().map(Path::to_path_buf);
        let content = options.into_content();
        let dependencies =
            analyze_script_dependencies(&content, media_type_for_script(path.as_deref()));
        let kind = match path {
            Some(path) => ScriptSourceKind::File { path },
            None => ScriptSourceKind::Inline,
        };
        Self {
            content,
            kind,
            dependencies,
        }
    }

    pub(crate) fn content(&self) -> &str {
        &self.content
    }

    pub(crate) fn path(&self) -> Option<&Path> {
        match &self.kind {
            ScriptSourceKind::Inline => None,
            ScriptSourceKind::File { path } => Some(path),
        }
    }

    pub(crate) fn dependencies(&self) -> ScriptDependencies {
        self.dependencies
    }

    pub(crate) fn description(&self) -> String {
        match self.path() {
            Some(path) => format!("file script at {}", path.display()),
            None => format!("inline script ({} bytes)", self.content().len()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::ScriptSource;
    use crate::options::ScriptOptions;
    use std::path::PathBuf;

    #[test]
    fn creates_inline_sources_from_inline_options() {
        let source = ScriptSource::from_options(ScriptOptions::inline(
            "export default () => 'inline';".to_string(),
        ));

        assert_eq!(source.content(), "export default () => 'inline';");
        assert_eq!(source.path(), None);
        assert!(!source.dependencies().needs_package_loader());
        assert_eq!(source.description(), "inline script (30 bytes)");
    }

    #[test]
    fn creates_file_sources_from_file_options() {
        let path = PathBuf::from("/tmp/belgie/scripts/main.ts");
        let source = ScriptSource::from_options(ScriptOptions::from_file(
            "export default () => 'file';".to_string(),
            path.clone(),
        ));

        assert_eq!(source.content(), "export default () => 'file';");
        assert_eq!(source.path(), Some(path.as_path()));
        assert!(!source.dependencies().needs_package_loader());
        assert_eq!(
            source.description(),
            "file script at /tmp/belgie/scripts/main.ts"
        );
    }

    #[test]
    fn records_inline_dependency_imports() {
        let source = ScriptSource::from_options(ScriptOptions::inline(
            r#"import isNumber from "npm:is-number@7.0.0"; export default () => isNumber(1);"#
                .to_string(),
        ));

        assert!(source.dependencies().needs_package_loader());
    }
}
