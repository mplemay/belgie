use std::path::{Path, PathBuf};

use super::dependencies::{analyze_parsed_script_dependencies, content_may_have_resolver_imports};
use super::signature::{self, RunSignature, media_type_for_script, run_signature_from_parsed};
use crate::options::ScriptOptions;

#[derive(Clone, Debug)]
pub(crate) struct ScriptSource {
    content: String,
    kind: ScriptSourceKind,
    media_type: deno_ast::MediaType,
    needs_package_loader: bool,
    run_signature: Option<RunSignature>,
}

#[derive(Clone, Debug)]
enum ScriptSourceKind {
    Inline { filename: Option<PathBuf> },
    File { path: PathBuf },
}

impl ScriptSource {
    pub(crate) fn from_options(options: ScriptOptions) -> Self {
        let filename = options.filename().map(Path::to_path_buf);
        let from_file = options.is_from_file();
        let content = options.into_content();
        let media_type = media_type_for_script(filename.as_deref());
        let parsed = signature::parse_script_module(&content, media_type);
        let needs_package_loader = parsed
            .as_ref()
            .filter(|_| content_may_have_resolver_imports(&content))
            .is_some_and(analyze_parsed_script_dependencies);
        let run_signature = parsed.as_ref().and_then(run_signature_from_parsed);
        let kind = match (from_file, filename) {
            (true, Some(path)) => ScriptSourceKind::File { path },
            (false, filename) => ScriptSourceKind::Inline { filename },
            (true, None) => unreachable!("file scripts always have a filename"),
        };
        Self {
            content,
            kind,
            media_type,
            needs_package_loader,
            run_signature,
        }
    }

    pub(crate) fn content(&self) -> &str {
        &self.content
    }

    pub(crate) fn filename(&self) -> Option<&Path> {
        match &self.kind {
            ScriptSourceKind::Inline { filename } => filename.as_deref(),
            ScriptSourceKind::File { path } => Some(path),
        }
    }

    pub(crate) fn media_type(&self) -> deno_ast::MediaType {
        self.media_type
    }

    pub(crate) fn needs_package_loader(&self) -> bool {
        self.needs_package_loader
    }

    pub(crate) fn run_signature(&self) -> Option<&RunSignature> {
        self.run_signature.as_ref()
    }

    pub(crate) fn description(&self) -> String {
        match &self.kind {
            ScriptSourceKind::File { path } => format!("file script at {}", path.display()),
            ScriptSourceKind::Inline {
                filename: Some(filename),
            } => format!(
                "inline script at {} ({} bytes)",
                filename.display(),
                self.content().len(),
            ),
            ScriptSourceKind::Inline { filename: None } => {
                format!("inline script ({} bytes)", self.content().len())
            }
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
            None,
        ));

        assert_eq!(source.content(), "export default () => 'inline';");
        assert_eq!(source.filename(), None);
        assert!(!source.needs_package_loader());
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
        assert_eq!(source.filename(), Some(path.as_path()));
        assert!(!source.needs_package_loader());
        assert_eq!(
            source.description(),
            "file script at /tmp/belgie/scripts/main.ts"
        );
    }

    #[test]
    fn records_inline_dependency_analysis_on_source() {
        let source = ScriptSource::from_options(ScriptOptions::inline(
            r#"import isNumber from "npm:is-number@7.0.0"; export default () => isNumber(1);"#
                .to_string(),
            None,
        ));

        assert!(source.needs_package_loader());
    }
}
