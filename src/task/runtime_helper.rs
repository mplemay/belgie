use std::path::PathBuf;
use std::sync::Mutex;

#[cfg(windows)]
use deno_core::anyhow::anyhow;
#[cfg(windows)]
use deno_core::error::AnyError;

static TASK_RUNTIME_PATH: Mutex<Option<PathBuf>> = Mutex::new(None);

pub(crate) fn configure_task_runtime_path(path: PathBuf) {
    *TASK_RUNTIME_PATH
        .lock()
        .expect("task runtime path lock should not be poisoned") = Some(path);
}

#[cfg(windows)]
pub(crate) fn resolve_task_runtime_exe() -> Result<PathBuf, AnyError> {
    let candidates = task_runtime_candidates();
    for candidate in &candidates {
        if candidate.is_file() {
            return Ok(candidate.clone());
        }
    }

    let attempts = candidates
        .iter()
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join(", ");
    Err(anyhow!(
        "Could not find packaged belgie-task-runtime helper. Tried: {attempts}"
    ))
}

#[cfg(windows)]
fn task_runtime_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(configured) = TASK_RUNTIME_PATH
        .lock()
        .expect("task runtime path lock should not be poisoned")
        .clone()
    {
        candidates.push(configured);
    }

    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            candidates.push(parent.join(TASK_RUNTIME_EXE_NAME));
            if parent.file_name().is_some_and(|name| name == "deps") {
                if let Some(target_dir) = parent.parent() {
                    candidates.push(target_dir.join(TASK_RUNTIME_EXE_NAME));
                }
            }
        }
    }

    candidates.push(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("src")
            .join("belgie")
            .join("_bin")
            .join(TASK_RUNTIME_EXE_NAME),
    );
    candidates
}

#[cfg(windows)]
const TASK_RUNTIME_EXE_NAME: &str = "belgie-task-runtime.exe";
