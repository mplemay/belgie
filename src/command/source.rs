use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub(crate) struct CommandSource {
    name: String,
    cwd: Option<PathBuf>,
    env: BTreeMap<String, String>,
    module: bool,
}

impl CommandSource {
    pub(crate) fn new(
        name: String,
        cwd: Option<PathBuf>,
        env: BTreeMap<String, String>,
        module: bool,
    ) -> Self {
        Self {
            name,
            cwd,
            env,
            module,
        }
    }

    pub(crate) fn name(&self) -> &str {
        &self.name
    }

    pub(crate) fn cwd(&self) -> Option<&Path> {
        self.cwd.as_deref()
    }

    pub(crate) fn env(&self) -> &BTreeMap<String, String> {
        &self.env
    }

    pub(crate) fn module(&self) -> bool {
        self.module
    }

    pub(crate) fn description(&self) -> String {
        match &self.cwd {
            Some(cwd) => format!("command {:?} in {}", self.name, cwd.display()),
            None => format!("command {:?}", self.name),
        }
    }
}
