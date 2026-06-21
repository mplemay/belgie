use std::path::{Path, PathBuf};

use deno_core::anyhow::{Context, bail};
use deno_core::error::AnyError;

pub(crate) fn materialize_node_modules(
    cwd: &Path,
    temp_node_modules: &Path,
) -> Result<Option<PathBuf>, AnyError> {
    let target = cwd.join("node_modules");
    if !temp_node_modules.is_dir() {
        return Ok(None);
    }

    let canonical_temp = normalize_canonical(temp_node_modules)?;

    match inspect_path_entry(&target)? {
        PathEntry::Missing => {}
        PathEntry::NotSymlink => conflicting_node_modules(&target)?,
        PathEntry::Symlink(resolved) => {
            if paths_equal(&resolved, temp_node_modules)? {
                return Ok(Some(target));
            }
            if normalize_canonical(&resolved).is_ok() {
                conflicting_node_modules(&target)?;
            }
            remove_symlink(&target)?;
        }
    }

    create_directory_symlink(&canonical_temp, &target)?;
    Ok(Some(target))
}

pub(crate) fn cleanup_materialized(path: &Path, expected_target: &Path) -> Result<(), AnyError> {
    match inspect_path_entry(path)? {
        PathEntry::Missing | PathEntry::NotSymlink => {}
        PathEntry::Symlink(resolved) => {
            if owned_symlink_should_remove(&resolved, expected_target)? {
                remove_symlink(path)?;
            }
        }
    }
    Ok(())
}

enum PathEntry {
    Missing,
    NotSymlink,
    Symlink(PathBuf),
}

fn conflicting_node_modules(target: &Path) -> Result<(), AnyError> {
    bail!(
        "{} already exists; remove it or use a different cwd",
        target.display()
    );
}

fn inspect_path_entry(path: &Path) -> Result<PathEntry, AnyError> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            let existing = std::fs::read_link(path)
                .with_context(|| format!("Reading symlink {}", path.display()))?;
            Ok(PathEntry::Symlink(resolve_symlink_target(path, &existing)))
        }
        Ok(_) => Ok(PathEntry::NotSymlink),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(PathEntry::Missing),
        Err(error) => Err(error).with_context(|| format!("Inspecting {}", path.display())),
    }
}

fn owned_symlink_should_remove(resolved: &Path, expected: &Path) -> Result<bool, AnyError> {
    paths_equal(resolved, expected)
}

fn paths_equal(left: &Path, right: &Path) -> Result<bool, AnyError> {
    match (normalize_canonical(left), normalize_canonical(right)) {
        (Ok(left), Ok(right)) => Ok(left == right),
        _ => Ok(false),
    }
}

fn normalize_canonical(path: &Path) -> Result<PathBuf, AnyError> {
    let absolute = std::path::absolute(path)
        .with_context(|| format!("Resolving absolute path for {}", path.display()))?;
    Ok(deno_path_util::strip_unc_prefix(
        absolute
            .canonicalize()
            .with_context(|| format!("Canonicalizing {}", path.display()))?,
    ))
}

fn remove_symlink(path: &Path) -> Result<(), AnyError> {
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

fn resolve_symlink_target(link_path: &Path, link_contents: &Path) -> PathBuf {
    if link_contents.is_absolute() {
        link_contents.to_path_buf()
    } else {
        link_path
            .parent()
            .expect("symlink path must have a parent")
            .join(link_contents)
    }
}

fn create_directory_symlink(source: &Path, target: &Path) -> Result<(), AnyError> {
    let context = format!(
        "Creating symlink from {} to {}",
        target.display(),
        source.display()
    );
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(source, target).with_context(|| context.clone())?;
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_dir(source, target).with_context(|| context)?;
    }
    Ok(())
}

#[cfg(test)]
pub(crate) fn create_dangling_dir_symlink(link: &Path, target: &Path) {
    #[cfg(unix)]
    std::os::unix::fs::symlink(target, link).unwrap();
    #[cfg(windows)]
    std::os::windows::fs::symlink_dir(target, link).unwrap();
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{
        cleanup_materialized, create_dangling_dir_symlink, materialize_node_modules,
        normalize_canonical, resolve_symlink_target,
    };

    fn symlink_points_to(link: &Path, expected: &Path) {
        let contents = std::fs::read_link(link).unwrap();
        let resolved = resolve_symlink_target(link, &contents);
        assert_eq!(
            normalize_canonical(&resolved).unwrap(),
            normalize_canonical(expected).unwrap()
        );
    }

    #[test]
    fn materialize_creates_symlink_when_absent() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let temp = root.path().join("temp");
        let temp_node_modules = temp.join("node_modules");
        std::fs::create_dir_all(&temp_node_modules).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();

        let materialized = materialize_node_modules(&cwd, &temp_node_modules)
            .expect("materialize should succeed")
            .expect("materialize should create symlink");

        assert_eq!(materialized, cwd.join("node_modules"));
        assert!(materialized.is_symlink());
        symlink_points_to(&materialized, &temp_node_modules);

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

        let first = materialize_node_modules(&cwd, &temp_node_modules)
            .expect("first materialize")
            .expect("first materialize should create symlink");
        let second = materialize_node_modules(&cwd, &temp_node_modules)
            .expect("second materialize")
            .expect("second materialize should return symlink");

        assert_eq!(first, second);
        cleanup_materialized(&first, &temp_node_modules).unwrap();
    }

    #[test]
    fn materialize_rejects_conflicting_symlink_when_target_changes() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let first_temp = root.path().join("temp-first").join("node_modules");
        let second_temp = root.path().join("temp-second").join("node_modules");
        std::fs::create_dir_all(&first_temp).unwrap();
        std::fs::create_dir_all(&second_temp).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();

        let first = materialize_node_modules(&cwd, &first_temp)
            .expect("first materialize")
            .expect("first materialize should create symlink");
        let error = materialize_node_modules(&cwd, &second_temp).unwrap_err();

        assert!(error.to_string().contains("already exists"));
        symlink_points_to(&first, &first_temp);

        cleanup_materialized(&first, &first_temp).unwrap();
    }

    #[test]
    fn materialize_rejects_conflicting_symlink() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let external = root.path().join("external").join("node_modules");
        let temp_node_modules = root.path().join("temp").join("node_modules");
        std::fs::create_dir_all(&external).unwrap();
        std::fs::create_dir_all(&temp_node_modules).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();

        create_dangling_dir_symlink(&cwd.join("node_modules"), &external);

        let symlink = cwd.join("node_modules");
        let original_link = std::fs::read_link(&symlink).unwrap();
        assert!(symlink.is_symlink());

        let error = materialize_node_modules(&cwd, &temp_node_modules).unwrap_err();
        assert!(error.to_string().contains("already exists"));
        assert_eq!(std::fs::read_link(&symlink).unwrap(), original_link);
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

        assert!(materialized.is_none());
        assert!(!cwd.join("node_modules").exists());
    }

    #[test]
    fn materialize_replaces_dangling_symlink() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let temp = root.path().join("temp");
        let temp_node_modules = temp.join("node_modules");
        let dangling_target = root.path().join("missing").join("node_modules");
        std::fs::create_dir_all(&temp_node_modules).unwrap();
        std::fs::create_dir_all(&cwd).unwrap();

        create_dangling_dir_symlink(&cwd.join("node_modules"), &dangling_target);

        let symlink = cwd.join("node_modules");
        assert!(symlink.is_symlink());
        assert!(!symlink.exists());

        let materialized = materialize_node_modules(&cwd, &temp_node_modules)
            .expect("materialize should succeed")
            .expect("materialize should create symlink");

        assert_eq!(materialized, symlink);
        assert!(materialized.is_symlink());
        assert!(materialized.exists());
        symlink_points_to(&materialized, &temp_node_modules);

        cleanup_materialized(&materialized, &temp_node_modules).unwrap();
        assert!(!materialized.exists());
    }

    #[test]
    fn cleanup_preserves_unrelated_dangling_symlink() {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("project");
        let expected_target = root.path().join("temp").join("node_modules");
        let dangling_target = root.path().join("missing").join("node_modules");
        std::fs::create_dir_all(&cwd).unwrap();

        create_dangling_dir_symlink(&cwd.join("node_modules"), &dangling_target);

        let symlink = cwd.join("node_modules");
        assert!(symlink.is_symlink());
        assert!(!symlink.exists());

        cleanup_materialized(&symlink, &expected_target).unwrap();
        assert!(symlink.is_symlink());
    }
}
