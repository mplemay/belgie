use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub(crate) struct RunTaskOptions {
    pub task_cwd: PathBuf,
    pub script: String,
    pub argv: Vec<String>,
    pub env: BTreeMap<String, String>,
    pub host: Option<String>,
    pub port: Option<u16>,
}

#[derive(Clone, Debug)]
pub(crate) struct TaskResult {
    pub exit_code: i32,
    pub stderr: Option<String>,
}

impl TaskResult {
    pub(crate) fn success(&self) -> bool {
        self.exit_code == 0
    }
}
