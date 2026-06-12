use std::path::PathBuf;

use deno_core::anyhow::{anyhow, bail};

pub(crate) fn resolve_deno_exe() -> Result<PathBuf, deno_core::error::AnyError> {
    if let Ok(path) = std::env::var("BELGIE_DENO") {
        let path = PathBuf::from(path);
        if path.is_file() {
            return Ok(path);
        }
        bail!(
            "BELGIE_DENO points to a missing executable: {}",
            path.display()
        );
    }

    let path = which::which("deno").map_err(|_| {
        anyhow!(
            "Could not find the deno executable on PATH. Install Deno or set BELGIE_DENO to its path."
        )
    })?;
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_deno_exe_errors_when_missing() {
        let previous = std::env::var_os("BELGIE_DENO");
        let previous_path = std::env::var_os("PATH");
        // SAFETY: test-only environment mutation on the main thread.
        unsafe {
            std::env::remove_var("BELGIE_DENO");
            std::env::set_var("PATH", "");
        }
        let result = resolve_deno_exe();
        // SAFETY: test-only environment restoration on the main thread.
        unsafe {
            if let Some(value) = previous {
                std::env::set_var("BELGIE_DENO", value);
            } else {
                std::env::remove_var("BELGIE_DENO");
            }
            if let Some(value) = previous_path {
                std::env::set_var("PATH", value);
            }
        }
        assert!(result.is_err());
        assert!(
            result
                .expect_err("deno should be missing")
                .to_string()
                .contains("deno executable")
        );
    }
}
