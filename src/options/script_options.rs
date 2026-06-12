use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub(crate) struct ScriptOptions {
    content: String,
    path: Option<PathBuf>,
}

impl ScriptOptions {
    pub(crate) fn inline(content: String) -> Self {
        Self {
            content,
            path: None,
        }
    }

    pub(crate) fn from_file(content: String, path: PathBuf) -> Self {
        Self {
            content,
            path: Some(path),
        }
    }

    pub(crate) fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    pub(crate) fn into_content(self) -> String {
        self.content
    }
}

#[cfg(test)]
mod tests {
    use super::ScriptOptions;
    use std::path::PathBuf;

    #[test]
    fn inline_options_keep_content_without_a_path() {
        let options = ScriptOptions::inline("export default () => 42;".to_string());

        assert_eq!(options.path(), None);
        assert_eq!(options.into_content(), "export default () => 42;");
    }

    #[test]
    fn file_options_keep_content_and_source_path() {
        let path = PathBuf::from("/tmp/belgie/main.ts");
        let options =
            ScriptOptions::from_file("export const run = () => 42;".to_string(), path.clone());

        assert_eq!(options.path(), Some(path.as_path()));
        assert_eq!(options.into_content(), "export const run = () => 42;");
    }
}
