use std::path::Path;

use deno_core::anyhow::Context;
use deno_core::error::AnyError;

pub(crate) fn remove_symlink(path: &Path) -> Result<(), AnyError> {
    let context = format!("Removing symlink {}", path.display());
    #[cfg(unix)]
    {
        std::fs::remove_file(path).with_context(|| context)
    }
    #[cfg(windows)]
    {
        match std::fs::remove_dir(path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotADirectory => {
                std::fs::remove_file(path).with_context(|| context)
            }
            Err(error) => Err(error).with_context(|| context),
        }
    }
}

pub(crate) fn remove_symlink_if_present(path: &Path) -> Result<(), AnyError> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => remove_symlink(path),
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error).with_context(|| format!("Inspecting {}", path.display())),
    }
}

pub(crate) fn create_directory_symlink(target: &Path, link: &Path) -> Result<(), AnyError> {
    let context = format!(
        "Creating symlink from {} to {}",
        link.display(),
        target.display()
    );
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(target, link).with_context(|| context.clone())?;
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_dir(target, link).with_context(|| context)?;
    }
    Ok(())
}
