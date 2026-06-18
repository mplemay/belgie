use std::path::PathBuf;

use deno_core::anyhow::{Context, bail};

const BELGIE_NODE_ENV: &str = "BELGIE_NODE";

pub(crate) fn resolve_node_exe() -> Result<PathBuf, deno_core::error::AnyError> {
    if let Ok(path) = std::env::var(BELGIE_NODE_ENV) {
        let path = PathBuf::from(path);
        if path.is_file() {
            return Ok(path);
        }
        bail!(
            "{BELGIE_NODE_ENV} points to a missing executable: {}",
            path.display()
        );
    }

    which::which("node").with_context(|| {
        format!(
            "Could not find the node executable on PATH. Install Node.js or set {BELGIE_NODE_ENV} to its path."
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn with_env_var<T>(name: &str, value: Option<&str>, f: impl FnOnce() -> T) -> T {
        let previous = std::env::var_os(name);

        // SAFETY: test-only environment mutation on the main thread.
        unsafe {
            match value {
                Some(value) => std::env::set_var(name, value),
                None => std::env::remove_var(name),
            }
        }
        let result = f();
        // SAFETY: test-only environment restoration on the main thread.
        unsafe {
            if let Some(value) = previous {
                std::env::set_var(name, value);
            } else {
                std::env::remove_var(name);
            }
        }

        result
    }

    #[test]
    fn resolve_node_exe_uses_env_override() {
        let temp_dir = tempfile::tempdir().unwrap();
        let node = temp_dir.path().join("node");
        std::fs::write(&node, "").unwrap();

        let result = with_env_var(
            BELGIE_NODE_ENV,
            Some(node.to_str().unwrap()),
            resolve_node_exe,
        );

        assert_eq!(result.unwrap(), node);
    }

    #[test]
    fn resolve_node_exe_errors_for_missing_env_override() {
        let result = with_env_var(
            BELGIE_NODE_ENV,
            Some("/missing/belgie-node"),
            resolve_node_exe,
        );

        assert!(result.unwrap_err().to_string().contains(BELGIE_NODE_ENV));
    }

    #[test]
    fn resolve_node_exe_errors_when_missing() {
        let result = with_env_var(BELGIE_NODE_ENV, None, || {
            with_env_var("PATH", Some(""), resolve_node_exe)
        });

        assert!(result.unwrap_err().to_string().contains("node executable"));
    }
}
