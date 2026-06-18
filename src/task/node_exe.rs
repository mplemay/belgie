use std::path::PathBuf;

use deno_core::anyhow::{anyhow, bail};

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

    which::which("node").map_err(|_| {
        anyhow!(
            "Could not find the node executable on PATH. Install Node.js or set {BELGIE_NODE_ENV} to its path."
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_node_exe_uses_env_override() {
        let temp_dir = tempfile::tempdir().unwrap();
        let node = temp_dir.path().join("node");
        std::fs::write(&node, "").unwrap();
        let previous = std::env::var_os(BELGIE_NODE_ENV);

        // SAFETY: test-only environment mutation on the main thread.
        unsafe {
            std::env::set_var(BELGIE_NODE_ENV, &node);
        }
        let result = resolve_node_exe();
        // SAFETY: test-only environment restoration on the main thread.
        unsafe {
            if let Some(value) = previous {
                std::env::set_var(BELGIE_NODE_ENV, value);
            } else {
                std::env::remove_var(BELGIE_NODE_ENV);
            }
        }

        assert_eq!(result.unwrap(), node);
    }

    #[test]
    fn resolve_node_exe_errors_for_missing_env_override() {
        let previous = std::env::var_os(BELGIE_NODE_ENV);

        // SAFETY: test-only environment mutation on the main thread.
        unsafe {
            std::env::set_var(BELGIE_NODE_ENV, "/missing/belgie-node");
        }
        let result = resolve_node_exe();
        // SAFETY: test-only environment restoration on the main thread.
        unsafe {
            if let Some(value) = previous {
                std::env::set_var(BELGIE_NODE_ENV, value);
            } else {
                std::env::remove_var(BELGIE_NODE_ENV);
            }
        }

        assert!(result.unwrap_err().to_string().contains(BELGIE_NODE_ENV));
    }

    #[test]
    fn resolve_node_exe_errors_when_missing() {
        let previous = std::env::var_os(BELGIE_NODE_ENV);
        let previous_path = std::env::var_os("PATH");

        // SAFETY: test-only environment mutation on the main thread.
        unsafe {
            std::env::remove_var(BELGIE_NODE_ENV);
            std::env::set_var("PATH", "");
        }
        let result = resolve_node_exe();
        // SAFETY: test-only environment restoration on the main thread.
        unsafe {
            if let Some(value) = previous {
                std::env::set_var(BELGIE_NODE_ENV, value);
            } else {
                std::env::remove_var(BELGIE_NODE_ENV);
            }
            if let Some(value) = previous_path {
                std::env::set_var("PATH", value);
            }
        }

        assert!(result.unwrap_err().to_string().contains("node executable"));
    }
}
