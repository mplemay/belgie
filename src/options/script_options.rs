use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub(crate) struct ScriptOptions {
    content: String,
    filename: Option<PathBuf>,
    from_file: bool,
}

impl ScriptOptions {
    pub(crate) fn inline(content: String, filename: Option<PathBuf>) -> Self {
        Self {
            content,
            filename,
            from_file: false,
        }
    }

    pub(crate) fn from_file(content: String, path: PathBuf) -> Self {
        Self {
            content,
            filename: Some(path),
            from_file: true,
        }
    }

    pub(crate) fn filename(&self) -> Option<&Path> {
        self.filename.as_deref()
    }

    pub(crate) fn is_from_file(&self) -> bool {
        self.from_file
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
        let options = ScriptOptions::inline("export default () => 42;".to_string(), None);

        assert_eq!(options.filename(), None);
        assert!(!options.is_from_file());
        assert_eq!(options.into_content(), "export default () => 42;");
    }

    #[test]
    fn inline_options_keep_virtual_filenames() {
        let filename = PathBuf::from("src/widget.tsx");
        let options = ScriptOptions::inline(
            "export default () => <main />;".to_string(),
            Some(filename.clone()),
        );

        assert_eq!(options.filename(), Some(filename.as_path()));
        assert!(!options.is_from_file());
    }

    #[test]
    fn file_options_keep_content_and_source_path() {
        let path = PathBuf::from("/tmp/belgie/main.ts");
        let options =
            ScriptOptions::from_file("export const run = () => 42;".to_string(), path.clone());

        assert_eq!(options.filename(), Some(path.as_path()));
        assert!(options.is_from_file());
        assert_eq!(options.into_content(), "export const run = () => 42;");
    }
}
