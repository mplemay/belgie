use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use deno_core::anyhow::{Context, bail};
use deno_core::error::AnyError;
use deno_core::serde_json;

use crate::embed::EmbedContextOptions;
use crate::synthetic_config::{
    is_registry_import_specifier, read_synthetic_config_imports, write_synthetic_config_document,
};
use crate::utils::symlink::remove_symlink_if_present;

pub(crate) const EMPTY_DENO_LOCK: &str = "{\"version\":\"5\"}\n";
const BELGIE_DIR: &str = ".belgie";
const LOCAL_FILE_DEPS_STATE: &str = "local-file-deps.json";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PackageDependency {
    alias: String,
    kind: PackageDependencyKind,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum PackageDependencyKind {
    ImportMap { specifier: String },
    LocalFile { target_path: PathBuf },
}

#[derive(Clone, Debug)]
pub(crate) struct EnvironmentInstallResult {
    pub lockfile: PathBuf,
    pub dependencies: usize,
}

#[derive(Clone, Debug)]
pub(crate) struct EnvironmentUpdateResult {
    pub lockfile: PathBuf,
    pub changes: Vec<EnvironmentUpdateChange>,
}

#[derive(Clone, Debug)]
pub(crate) struct EnvironmentUpdateChange {
    pub name: String,
    pub previous: String,
    pub updated: String,
}

pub(crate) struct EnvironmentUpdateRequest {
    pub cwd: PathBuf,
    pub config_file: PathBuf,
    pub lockfile: PathBuf,
    pub dependencies: usize,
    pub packages: Vec<String>,
    pub latest: bool,
    pub lockfile_only: bool,
    pub options: EmbedContextOptions,
}

pub(crate) fn dependencies_from_mapping(
    workspace: &Path,
    dependencies: BTreeMap<String, String>,
) -> Result<Vec<PackageDependency>, AnyError> {
    dependencies
        .into_iter()
        .map(|(alias, specifier)| normalize_dependency(workspace, &alias, &specifier))
        .collect()
}

pub(crate) fn write_synthetic_config(
    path: &Path,
    dependencies: &[PackageDependency],
) -> Result<(), AnyError> {
    let imports = synthetic_imports(dependencies)?;
    let node_modules_dir = if requires_manual_node_modules(dependencies) {
        "manual"
    } else {
        "auto"
    };
    let config = serde_json::json!({
      "imports": imports,
      "nodeModulesDir": node_modules_dir,
    });
    write_synthetic_config_document(path, &config)
}

fn synthetic_imports(
    dependencies: &[PackageDependency],
) -> Result<BTreeMap<String, String>, AnyError> {
    let mut imports = BTreeMap::new();
    for dep in dependencies {
        match &dep.kind {
            PackageDependencyKind::ImportMap { specifier } => {
                imports.insert(dep.alias.clone(), specifier.clone());
            }
            PackageDependencyKind::LocalFile { target_path } => {
                let entrypoint = local_file_dependency_entrypoint(target_path)?;
                let entrypoint_rel = entrypoint
                    .strip_prefix(target_path)
                    .unwrap_or_else(|_| Path::new("index.js"));
                let entrypoint_path = entrypoint_rel
                    .components()
                    .map(|component| component.as_os_str().to_string_lossy())
                    .collect::<Vec<_>>()
                    .join("/");
                imports.insert(
                    dep.alias.clone(),
                    format!("./node_modules/{}/{}", dep.alias, entrypoint_path),
                );
                imports.insert(
                    format!("{}/", dep.alias),
                    format!("./node_modules/{}/", dep.alias),
                );
            }
        }
    }
    Ok(imports)
}

fn local_file_dependency_entrypoint(target_path: &Path) -> Result<PathBuf, AnyError> {
    let package_json_path = target_path.join("package.json");
    if !package_json_path.is_file() {
        return Ok(target_path.join("index.js"));
    }
    let text = std::fs::read_to_string(&package_json_path)
        .with_context(|| format!("Reading {}", package_json_path.display()))?;
    let package_json: serde_json::Value = serde_json::from_str(&text)
        .with_context(|| format!("Parsing {}", package_json_path.display()))?;
    let entrypoint = package_json
        .get("exports")
        .and_then(package_export_entrypoint)
        .or_else(|| {
            package_json
                .get("module")
                .and_then(serde_json::Value::as_str)
        })
        .or_else(|| package_json.get("main").and_then(serde_json::Value::as_str))
        .unwrap_or("index.js");
    Ok(target_path.join(entrypoint))
}

fn package_export_entrypoint(value: &serde_json::Value) -> Option<&str> {
    if let Some(entrypoint) = value.as_str() {
        return Some(entrypoint);
    }
    let object = value.as_object()?;
    if let Some(dot_export) = object.get(".")
        && let Some(entrypoint) = package_export_entrypoint(dot_export)
    {
        return Some(entrypoint);
    }
    ["import", "module", "default", "require"]
        .into_iter()
        .find_map(|condition| object.get(condition).and_then(package_export_entrypoint))
}

fn remove_legacy_synthetic_package_json(path: &Path) -> Result<(), AnyError> {
    if !path.is_file() {
        return Ok(());
    }
    let text =
        std::fs::read_to_string(path).with_context(|| format!("Reading {}", path.display()))?;
    let package_json: serde_json::Value =
        serde_json::from_str(&text).with_context(|| format!("Parsing {}", path.display()))?;
    if is_legacy_belgie_synthetic_package_json(&package_json) {
        std::fs::remove_file(path)
            .with_context(|| format!("Removing legacy synthetic {}", path.display()))?;
    }
    Ok(())
}

pub(crate) fn sync_local_file_dependency_symlinks(
    install_root: &Path,
    node_modules_root: &Path,
    dependencies: &[PackageDependency],
) -> Result<(), AnyError> {
    remove_legacy_synthetic_package_json(&install_root.join("package.json"))?;

    let current = local_file_dependencies(dependencies);
    let previous = read_tracked_local_file_aliases(install_root)?;

    for alias in &previous {
        if current.contains_key(alias) {
            continue;
        }
        remove_installed_local_package(&node_modules_root.join(alias))?;
    }

    if current.is_empty() {
        remove_tracked_local_file_aliases(install_root)?;
        return Ok(());
    }

    std::fs::create_dir_all(node_modules_root)
        .with_context(|| format!("Creating {}", node_modules_root.display()))?;
    for (alias, target_path) in &current {
        install_package_dir(target_path, &node_modules_root.join(alias))?;
    }
    write_tracked_local_file_aliases(install_root, current.keys())
}

pub(crate) fn has_local_file_dependencies(dependencies: &[PackageDependency]) -> bool {
    dependencies
        .iter()
        .any(|dep| matches!(dep.kind, PackageDependencyKind::LocalFile { .. }))
}

pub(crate) fn requires_manual_node_modules(dependencies: &[PackageDependency]) -> bool {
    has_local_file_dependencies(dependencies)
        && dependencies
            .iter()
            .all(|dep| matches!(dep.kind, PackageDependencyKind::LocalFile { .. }))
}

pub(crate) async fn install_environment_packages(
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    dependencies: usize,
    lockfile_only: bool,
    options: EmbedContextOptions,
) -> Result<EnvironmentInstallResult, AnyError> {
    if dependencies > 0 {
        crate::embed::install_packages_with_options(
            cwd,
            config_file,
            lockfile.clone(),
            lockfile_only,
            options,
        )
        .await?;
    }
    Ok(EnvironmentInstallResult {
        lockfile,
        dependencies,
    })
}

pub(crate) async fn update_environment_packages(
    request: EnvironmentUpdateRequest,
) -> Result<EnvironmentUpdateResult, AnyError> {
    if request.dependencies == 0 {
        return Ok(EnvironmentUpdateResult {
            lockfile: request.lockfile,
            changes: Vec::new(),
        });
    }

    let before = read_synthetic_config_imports(&request.config_file)?;
    crate::embed::update_packages(
        request.cwd,
        request.config_file.clone(),
        request.lockfile.clone(),
        request.packages,
        request.latest,
        request.lockfile_only,
        request.options,
    )
    .await?;
    let after = read_synthetic_config_imports(&request.config_file)?;

    Ok(EnvironmentUpdateResult {
        lockfile: request.lockfile,
        changes: update_changes_from_imports(&before, &after),
    })
}

fn normalize_dependency(
    workspace: &Path,
    alias: &str,
    raw_value: &str,
) -> Result<PackageDependency, AnyError> {
    if let Some(path) = raw_value.strip_prefix("file:") {
        if path.is_empty() {
            bail!("Belgie dependency '{alias}' must provide a non-empty file: path");
        }
        return Ok(PackageDependency {
            alias: alias.to_string(),
            kind: PackageDependencyKind::LocalFile {
                target_path: normalize_workspace_path(workspace, path)?,
            },
        });
    }

    let specifier = if is_registry_import_specifier(raw_value) {
        raw_value.to_string()
    } else {
        format!("npm:{alias}@{raw_value}")
    };
    Ok(PackageDependency {
        alias: alias.to_string(),
        kind: PackageDependencyKind::ImportMap { specifier },
    })
}

fn normalize_workspace_path(workspace: &Path, path: &str) -> Result<PathBuf, AnyError> {
    let raw_path = Path::new(path);
    let target = if raw_path.is_absolute() {
        raw_path.to_path_buf()
    } else {
        workspace.join(raw_path)
    };
    std::path::absolute(&target)
        .map(deno_path_util::strip_unc_prefix)
        .with_context(|| format!("Resolving file dependency path {}", target.display()))
}

fn local_file_dependencies(dependencies: &[PackageDependency]) -> BTreeMap<String, PathBuf> {
    dependencies
        .iter()
        .filter_map(|dep| {
            let PackageDependencyKind::LocalFile { target_path } = &dep.kind else {
                return None;
            };
            Some((dep.alias.clone(), target_path.clone()))
        })
        .collect()
}

fn local_file_deps_state_path(install_root: &Path) -> PathBuf {
    install_root.join(BELGIE_DIR).join(LOCAL_FILE_DEPS_STATE)
}

fn read_tracked_local_file_aliases(install_root: &Path) -> Result<Vec<String>, AnyError> {
    let path = local_file_deps_state_path(install_root);
    if !path.is_file() {
        return Ok(Vec::new());
    }
    let text =
        std::fs::read_to_string(&path).with_context(|| format!("Reading {}", path.display()))?;
    serde_json::from_str(&text).with_context(|| format!("Parsing {}", path.display()))
}

fn write_tracked_local_file_aliases<'a>(
    install_root: &Path,
    aliases: impl IntoIterator<Item = &'a String>,
) -> Result<(), AnyError> {
    let path = local_file_deps_state_path(install_root);
    let parent = path.parent().expect("state file path must have a parent");
    std::fs::create_dir_all(parent).with_context(|| format!("Creating {}", parent.display()))?;
    let aliases = aliases.into_iter().cloned().collect::<Vec<_>>();
    let text = serde_json::to_string_pretty(&aliases)?;
    std::fs::write(&path, format!("{text}\n"))
        .with_context(|| format!("Writing {}", path.display()))
}

fn remove_tracked_local_file_aliases(install_root: &Path) -> Result<(), AnyError> {
    let path = local_file_deps_state_path(install_root);
    if path.is_file() {
        std::fs::remove_file(&path).with_context(|| format!("Removing {}", path.display()))?;
    }
    let belgie_dir = install_root.join(BELGIE_DIR);
    if belgie_dir.is_dir()
        && std::fs::read_dir(&belgie_dir)
            .with_context(|| format!("Reading {}", belgie_dir.display()))?
            .next()
            .transpose()?
            .is_none()
    {
        std::fs::remove_dir(&belgie_dir)
            .with_context(|| format!("Removing {}", belgie_dir.display()))?;
    }
    Ok(())
}

fn is_legacy_belgie_synthetic_package_json(value: &serde_json::Value) -> bool {
    let Some(obj) = value.as_object() else {
        return false;
    };
    if obj.get("private") != Some(&serde_json::Value::Bool(true)) {
        return false;
    }
    if !obj
        .keys()
        .all(|key| key == "private" || key == "dependencies")
    {
        return false;
    }
    let Some(deps) = obj.get("dependencies").and_then(|value| value.as_object()) else {
        return false;
    };
    deps.values().all(|value| {
        value
            .as_str()
            .is_some_and(|specifier| specifier.starts_with("file:"))
    })
}

fn remove_installed_local_package(path: &Path) -> Result<(), AnyError> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => remove_symlink_if_present(path),
        Ok(metadata) if metadata.is_dir() => std::fs::remove_dir_all(path)
            .with_context(|| format!("Removing {}", path.display()))
            .map(|_| ()),
        Ok(_) => std::fs::remove_file(path)
            .with_context(|| format!("Removing {}", path.display()))
            .map(|_| ()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error).with_context(|| format!("Inspecting {}", path.display())),
    }
}

fn install_package_dir(source: &Path, dest: &Path) -> Result<(), AnyError> {
    remove_installed_local_package(dest)?;
    copy_dir_recursive(source, dest)
}

fn copy_dir_recursive(source: &Path, dest: &Path) -> Result<(), AnyError> {
    std::fs::create_dir_all(dest).with_context(|| format!("Creating {}", dest.display()))?;
    for entry in
        std::fs::read_dir(source).with_context(|| format!("Reading {}", source.display()))?
    {
        let entry = entry.with_context(|| format!("Reading {}", source.display()))?;
        let target = dest.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_recursive(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), &target).with_context(|| {
                format!("Copying {} to {}", entry.path().display(), target.display())
            })?;
        }
    }
    Ok(())
}

fn update_changes_from_imports(
    before: &serde_json::Map<String, serde_json::Value>,
    after: &serde_json::Map<String, serde_json::Value>,
) -> Vec<EnvironmentUpdateChange> {
    after
        .iter()
        .filter_map(|(alias, updated)| {
            let previous = before.get(alias)?.as_str()?;
            let updated = updated.as_str()?;
            (previous != updated).then(|| EnvironmentUpdateChange {
                name: alias.clone(),
                previous: previous.to_string(),
                updated: updated.to_string(),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn normalizes_unprefixed_dependencies_to_npm_imports() {
        let workspace = Path::new("/project");
        let dep = normalize_dependency(workspace, "react", "^19").unwrap();

        assert_eq!(dep.alias, "react");
        assert_eq!(
            dep.kind,
            PackageDependencyKind::ImportMap {
                specifier: "npm:react@^19".to_string()
            }
        );
    }

    #[test]
    fn preserves_explicit_jsr_specifiers() {
        let workspace = Path::new("/project");
        let dep = normalize_dependency(workspace, "@std/path", "jsr:@std/path@^1").unwrap();

        assert_eq!(
            dep.kind,
            PackageDependencyKind::ImportMap {
                specifier: "jsr:@std/path@^1".to_string()
            }
        );
    }

    #[test]
    fn normalizes_file_dependencies_relative_to_workspace() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("project");
        let dep =
            normalize_dependency(&workspace, "local-pkg", "file:./packages/local-pkg").unwrap();

        assert_eq!(dep.alias, "local-pkg");
        let expected = deno_path_util::strip_unc_prefix(
            std::path::absolute(workspace.join("packages").join("local-pkg")).unwrap(),
        );
        assert_eq!(
            dep.kind,
            PackageDependencyKind::LocalFile {
                target_path: expected,
            }
        );
    }

    #[test]
    fn rejects_empty_file_dependencies() {
        let workspace = Path::new("/project");
        let error = normalize_dependency(workspace, "local-pkg", "file:").unwrap_err();

        assert!(error.to_string().contains("non-empty file: path"));
    }

    #[test]
    fn synthetic_config_contains_imports_and_enables_isolated_node_modules_dir() {
        let temp_dir = tempfile::tempdir().unwrap();
        let config_path = temp_dir.path().join("deno.json");
        let dependencies = vec![normalize_dependency(temp_dir.path(), "react", "^19").unwrap()];

        write_synthetic_config(&config_path, &dependencies).unwrap();

        let text = fs::read_to_string(config_path).unwrap();
        let config: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(config["imports"]["react"], "npm:react@^19");
        assert_eq!(config["nodeModulesDir"], "auto");
    }

    #[test]
    fn synthetic_config_uses_manual_node_modules_for_file_only_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::create_dir_all(temp_dir.path().join("local-pkg")).unwrap();
        let config_path = temp_dir.path().join("deno.json");
        let dependencies =
            vec![normalize_dependency(temp_dir.path(), "local-pkg", "file:./local-pkg").unwrap()];

        write_synthetic_config(&config_path, &dependencies).unwrap();

        let text = fs::read_to_string(config_path).unwrap();
        let config: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(
            config["imports"]["local-pkg"],
            "./node_modules/local-pkg/index.js"
        );
        assert_eq!(config["imports"]["local-pkg/"], "./node_modules/local-pkg/");
        assert_eq!(config["nodeModulesDir"], "manual");
    }

    #[test]
    fn synthetic_config_uses_auto_node_modules_for_mixed_file_and_import_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::create_dir_all(temp_dir.path().join("local-pkg")).unwrap();
        let config_path = temp_dir.path().join("deno.json");
        let dependencies = vec![
            normalize_dependency(temp_dir.path(), "react", "^19").unwrap(),
            normalize_dependency(temp_dir.path(), "local-pkg", "file:./local-pkg").unwrap(),
        ];

        write_synthetic_config(&config_path, &dependencies).unwrap();

        let text = fs::read_to_string(config_path).unwrap();
        let config: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(config["imports"]["react"], "npm:react@^19");
        assert_eq!(
            config["imports"]["local-pkg"],
            "./node_modules/local-pkg/index.js"
        );
        assert_eq!(config["imports"]["local-pkg/"], "./node_modules/local-pkg/");
        assert_eq!(config["nodeModulesDir"], "auto");
    }

    #[test]
    fn sync_local_file_dependency_symlinks_creates_package_link() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let local_pkg = workspace.join("local-pkg");
        fs::create_dir_all(&local_pkg).unwrap();
        fs::write(local_pkg.join("index.js"), "export const answer = 42;\n").unwrap();
        let node_modules = install_root.join("node_modules");
        let dependencies =
            vec![normalize_dependency(&workspace, "local-pkg", "file:./local-pkg").unwrap()];

        sync_local_file_dependency_symlinks(&install_root, &node_modules, &dependencies).unwrap();

        let installed = node_modules.join("local-pkg");
        assert!(installed.is_dir());
        assert!(!installed.is_symlink());
        assert_eq!(
            fs::read_to_string(installed.join("index.js")).unwrap(),
            "export const answer = 42;\n"
        );
        assert!(!install_root.join("package.json").exists());
        assert!(
            install_root
                .join(BELGIE_DIR)
                .join(LOCAL_FILE_DEPS_STATE)
                .is_file()
        );
    }

    #[test]
    fn sync_local_file_dependency_symlinks_creates_scoped_package_link() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let local_pkg = workspace.join("packages").join("@scope").join("pkg");
        fs::create_dir_all(&local_pkg).unwrap();
        fs::write(local_pkg.join("index.js"), "export const answer = 42;\n").unwrap();
        let node_modules = install_root.join("node_modules");
        let dependencies = vec![
            normalize_dependency(&workspace, "@scope/pkg", "file:./packages/@scope/pkg").unwrap(),
        ];

        sync_local_file_dependency_symlinks(&install_root, &node_modules, &dependencies).unwrap();

        let installed = node_modules.join("@scope").join("pkg");
        assert!(installed.is_dir());
        assert!(!installed.is_symlink());
        assert_eq!(
            fs::read_to_string(installed.join("index.js")).unwrap(),
            "export const answer = 42;\n"
        );
    }

    #[test]
    fn sync_local_file_dependency_symlinks_removes_stale_alias() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let local_pkg = workspace.join("local-pkg");
        fs::create_dir_all(&local_pkg).unwrap();
        let node_modules = install_root.join("node_modules");
        let file_dependencies =
            vec![normalize_dependency(&workspace, "local-pkg", "file:./local-pkg").unwrap()];
        sync_local_file_dependency_symlinks(&install_root, &node_modules, &file_dependencies)
            .unwrap();

        let npm_dependencies = vec![normalize_dependency(&workspace, "react", "^19").unwrap()];
        sync_local_file_dependency_symlinks(&install_root, &node_modules, &npm_dependencies)
            .unwrap();

        assert!(!node_modules.join("local-pkg").exists());
        assert!(
            !install_root
                .join(BELGIE_DIR)
                .join(LOCAL_FILE_DEPS_STATE)
                .exists()
        );
    }

    #[test]
    fn remove_legacy_synthetic_package_json_deletes_old_belgie_manifest() {
        let temp_dir = tempfile::tempdir().unwrap();
        let package_json_path = temp_dir.path().join("package.json");
        fs::write(
            &package_json_path,
            r#"{
  "private": true,
  "dependencies": {
    "local-pkg": "file:./local-pkg"
  }
}
"#,
        )
        .unwrap();

        remove_legacy_synthetic_package_json(&package_json_path).unwrap();

        assert!(!package_json_path.exists());
    }

    #[test]
    fn remove_legacy_synthetic_package_json_preserves_unrelated_manifests() {
        let temp_dir = tempfile::tempdir().unwrap();
        let package_json_path = temp_dir.path().join("package.json");
        let contents = r#"{ "name": "project", "scripts": { "test": "node test.js" } }"#;
        fs::write(&package_json_path, contents).unwrap();

        remove_legacy_synthetic_package_json(&package_json_path).unwrap();

        assert_eq!(fs::read_to_string(package_json_path).unwrap(), contents);
    }

    #[test]
    fn records_updated_import_changes() {
        let before = serde_json::Map::from_iter([
            (
                "react".to_string(),
                serde_json::Value::String("npm:react@^18".to_string()),
            ),
            (
                "std_path".to_string(),
                serde_json::Value::String("jsr:@std/path@^1".to_string()),
            ),
        ]);
        let after = serde_json::Map::from_iter([
            (
                "react".to_string(),
                serde_json::Value::String("npm:react@^19".to_string()),
            ),
            (
                "std_path".to_string(),
                serde_json::Value::String("jsr:@std/path@^1".to_string()),
            ),
        ]);

        let changes = update_changes_from_imports(&before, &after);

        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].name, "react");
        assert_eq!(changes[0].previous, "npm:react@^18");
        assert_eq!(changes[0].updated, "npm:react@^19");
    }
}
