use std::path::{Path, PathBuf};

use deno_ast::MediaType;

use super::dependencies::{analyze_parsed_script_dependencies, content_may_have_resolver_imports};
use super::signature::{self, RunSignature, run_signature_from_parsed};
use crate::options::ScriptOptions;

const INLINE_REACT_IMPORT_SOURCE: &str = "npm:react@19.2.6";

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
    Inline,
    File { path: PathBuf },
}

impl ScriptSource {
    pub(crate) fn from_options(options: ScriptOptions) -> Self {
        let path = options.path().map(Path::to_path_buf);
        let content = options.into_content();
        let (media_type, parsed) = parsed_source(&content, path.as_deref());
        let needs_package_loader = media_type == MediaType::Tsx
            || parsed
                .as_ref()
                .filter(|_| content_may_have_resolver_imports(&content))
                .is_some_and(analyze_parsed_script_dependencies);
        let run_signature = parsed.as_ref().and_then(run_signature_from_parsed);
        let kind = match path {
            Some(path) => ScriptSourceKind::File { path },
            None => ScriptSourceKind::Inline,
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
            ScriptSourceKind::Inline => None,
            ScriptSourceKind::File { path } => Some(path),
        }
    }

    pub(crate) fn media_type(&self) -> deno_ast::MediaType {
        self.media_type
    }

    pub(crate) fn execution_content(&self) -> String {
        if matches!(&self.kind, ScriptSourceKind::Inline) && self.media_type == MediaType::Tsx {
            format!(
                "/** @jsxRuntime automatic */\n/** @jsxImportSource {INLINE_REACT_IMPORT_SOURCE} */\n{}",
                self.content,
            )
        } else {
            self.content.clone()
        }
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
            ScriptSourceKind::Inline => {
                format!("inline script ({} bytes)", self.content().len())
            }
        }
    }
}

fn parsed_source(
    content: &str,
    path: Option<&Path>,
) -> (MediaType, Option<deno_ast::ParsedSource>) {
    if let Some(path) = path {
        let media_type = MediaType::from_path(path);
        return (
            media_type,
            signature::parse_script_module(content, media_type),
        );
    }

    if let Some(parsed) = signature::parse_script_module(content, MediaType::TypeScript) {
        return (MediaType::TypeScript, Some(parsed));
    }

    (
        MediaType::Tsx,
        signature::parse_script_module(content, MediaType::Tsx),
    )
}

#[cfg(test)]
mod tests {
    use deno_ast::MediaType;

    use super::ScriptSource;
    use crate::options::ScriptOptions;
    use std::path::PathBuf;

    #[test]
    fn creates_inline_sources_from_inline_options() {
        let source = ScriptSource::from_options(ScriptOptions::inline(
            "export default () => 'inline';".to_string(),
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
        ));

        assert!(source.needs_package_loader());
    }

    #[test]
    fn detects_inline_tsx_after_typescript_parse_fails() {
        let source = ScriptSource::from_options(ScriptOptions::inline(
            "export default () => <main>Hello</main>;".to_string(),
        ));

        assert_eq!(source.media_type(), MediaType::Tsx);
        assert!(source.needs_package_loader());
        assert!(source.execution_content().contains("@jsxRuntime automatic"));
        assert!(
            source
                .execution_content()
                .contains("@jsxImportSource npm:react@19.2.6"),
        );
    }

    #[test]
    fn preserves_typescript_generic_syntax_before_trying_tsx() {
        let source = ScriptSource::from_options(ScriptOptions::inline(
            "const identity = <T>(value: T): T => value; export default () => identity(42);"
                .to_string(),
        ));

        assert_eq!(source.media_type(), MediaType::TypeScript);
        assert!(!source.execution_content().contains("@jsxRuntime"));
    }
}
