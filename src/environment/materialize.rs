use std::path::{Path, PathBuf};

use deno_core::anyhow::{Context, bail};
use deno_core::error::AnyError;

pub(crate) fn materialize_node_modules(
    cwd: &Path,
    temp_node_modules: &Path,
) -> Result<PathBuf, AnyError> {
    if !temp_node_modules.is_dir() {
        return Ok(cwd.join("node_modules"));
    }

    let target = cwd.join("node_modules");
    let canonical_temp = temp_node_modules
        .canonicalize()
        .with_context(|| format!("Canonicalizing {}", temp_node_modules.display()))?;

    if target.exists() {
        if target.is_symlink() {
            let existing = std::fs::read_link(&target)
                .with_context(|| format!("Reading symlink {}", target.display()))?;
            let canonical_existing = if existing.is_absolute() {
                existing
            } else {
                target.parent().unwrap_or(cwd).join(existing)
            };
            let canonical_existing = canonical_existing
                .canonicalize()
                .with_context(|| format!("Canonicalizing {}", canonical_existing.display()))?;
            if canonical_existing == canonical_temp {
                return Ok(target);
            }
            std::fs::remove_file(&target)
                .with_context(|| format!("Removing symlink {}", target.display()))?;
        } else {
            bail!(
                "{} already exists; remove it or use a different cwd",
                target.display()
            );
        }
    }

    create_directory_symlink(&canonical_temp, &target)?;
    Ok(target)
}

pub(crate) fn cleanup_materialized(path: &Path, expected_target: &Path) -> Result<(), AnyError> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            let existing = std::fs::read_link(path)
                .with_context(|| format!("Reading symlink {}", path.display()))?;
            let canonical_existing = if existing.is_absolute() {
                existing
            } else {
                path.parent()
                    .unwrap_or_else(|| Path::new("."))
                    .join(existing)
            };
            let canonical_existing = canonical_existing
                .canonicalize()
                .with_context(|| format!("Canonicalizing {}", canonical_existing.display()))?;
            let canonical_expected = expected_target
                .canonicalize()
                .with_context(|| format!("Canonicalizing {}", expected_target.display()))?;
            if canonical_existing == canonical_expected {
                std::fs::remove_file(path)
                    .with_context(|| format!("Removing symlink {}", path.display()))?;
            }
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(error).with_context(|| format!("Inspecting {}", path.display()));
        }
    }
    Ok(())
}

fn create_directory_symlink(source: &Path, target: &Path) -> Result<(), AnyError> {
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(source, target).with_context(|| {
            format!(
                "Creating symlink from {} to {}",
                target.display(),
                source.display()
            )
        })?;
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_dir(source, target).with_context(|| {
            format!(
                "Creating symlink from {} to {}",
                target.display(),
                source.display()
            )
        })?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{cleanup_materialized, materialize_node_modules};

    #[test]
    fn materialize_creates_symlink_when_absent() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let temp = root.path().join("temp");
        let temp_node_modules = temp.join("node_modules");
        std::fs::create_dir_all(&temp_node_modules).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();

        let materialized =
            materialize_node_modules(&cwd, &temp_node_modules).expect("materialize should succeed");

        assert_eq!(materialized, cwd.join("node_modules"));
        assert!(materialized.is_symlink());
        assert_eq!(
            std::fs::read_link(&materialized).unwrap(),
            temp_node_modules.canonicalize().unwrap()
        );

        cleanup_materialized(&materialized, &temp_node_modules).unwrap();
        assert!(!materialized.exists());
    }

    #[test]
    fn materialize_is_idempotent_for_same_target() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let temp = root.path().join("temp");
        let temp_node_modules = temp.join("node_modules");
        std::fs::create_dir_all(&temp_node_modules).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();

        let first = materialize_node_modules(&cwd, &temp_node_modules).expect("first materialize");
        let second =
            materialize_node_modules(&cwd, &temp_node_modules).expect("second materialize");

        assert_eq!(first, second);
        cleanup_materialized(&first, &temp_node_modules).unwrap();
    }

    #[test]
    fn materialize_replaces_symlink_when_target_changes() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let first_temp = root.path().join("temp-first").join("node_modules");
        let second_temp = root.path().join("temp-second").join("node_modules");
        std::fs::create_dir_all(&first_temp).unwrap();
        std::fs::create_dir_all(&second_temp).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();

        let first = materialize_node_modules(&cwd, &first_temp).expect("first materialize");
        let second = materialize_node_modules(&cwd, &second_temp).expect("second materialize");

        assert_eq!(first, second);
        assert_eq!(
            std::fs::read_link(&second).unwrap(),
            second_temp.canonicalize().unwrap()
        );

        cleanup_materialized(&second, &second_temp).unwrap();
    }

    #[test]
    fn materialize_rejects_conflicting_directory() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let temp = root.path().join("temp");
        let temp_node_modules = temp.join("node_modules");
        std::fs::create_dir_all(&temp_node_modules).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();
        std::fs::create_dir_all(cwd.join("node_modules")).unwrap();

        let error = materialize_node_modules(&cwd, &temp_node_modules).unwrap_err();
        assert!(error.to_string().contains("already exists"));
    }

    #[test]
    fn materialize_skips_when_temp_node_modules_missing() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let temp_node_modules = root.path().join("temp").join("node_modules");
        std::fs::create_dir_all(&cwd).unwrap();

        let materialized =
            materialize_node_modules(&cwd, &temp_node_modules).expect("materialize should noop");

        assert_eq!(materialized, cwd.join("node_modules"));
        assert!(!materialized.exists());
    }
}
