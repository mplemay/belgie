use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub struct CommandSource {
    name: String,
    cwd: Option<PathBuf>,
    env: BTreeMap<String, String>,
    module: bool,
}

impl CommandSource {
    pub fn new(
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

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn cwd(&self) -> Option<&Path> {
        self.cwd.as_deref()
    }

    pub fn env(&self) -> &BTreeMap<String, String> {
        &self.env
    }

    pub fn module(&self) -> bool {
        self.module
    }

    pub fn description(&self) -> String {
        match &self.cwd {
            Some(cwd) => format!("command {:?} in {}", self.name, cwd.display()),
            None => format!("command {:?}", self.name),
        }
    }
}
