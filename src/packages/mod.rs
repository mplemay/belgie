use std::collections::BTreeMap;
use std::path::{Component, Path, PathBuf};

use deno_core::anyhow::{Context, bail};
use deno_core::error::AnyError;
use deno_core::serde_json;

use crate::embed::EmbedContextOptions;

pub(crate) const EMPTY_DENO_LOCK: &str = "{\"version\":\"5\"}\n";

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
    let imports = dependencies
        .iter()
        .filter_map(|dep| {
            let PackageDependencyKind::ImportMap { specifier } = &dep.kind else {
                return None;
            };
            Some((dep.alias.clone(), specifier.clone()))
        })
        .collect::<BTreeMap<_, _>>();
    let node_modules_dir = if has_local_file_dependencies(dependencies) {
        "manual"
    } else {
        "auto"
    };
    let config = serde_json::json!({
      "imports": imports,
      "nodeModulesDir": node_modules_dir,
    });
    let text = serde_json::to_string_pretty(&config)?;
    std::fs::write(path, format!("{text}\n"))
        .with_context(|| format!("Writing {}", path.display()))?;
    Ok(())
}

pub(crate) fn write_synthetic_package_json(
    path: &Path,
    install_root: &Path,
    dependencies: &[PackageDependency],
) -> Result<(), AnyError> {
    let local_dependencies = dependencies
        .iter()
        .filter_map(|dep| {
            let PackageDependencyKind::LocalFile { target_path } = &dep.kind else {
                return None;
            };
            Some((
                dep.alias.clone(),
                format!(
                    "file:{}",
                    path_for_package_json(relative_path(install_root, target_path))
                ),
            ))
        })
        .collect::<BTreeMap<_, _>>();
    if local_dependencies.is_empty() {
        return Ok(());
    }
    let package_json = serde_json::json!({
      "private": true,
      "dependencies": local_dependencies,
    });
    let text = serde_json::to_string_pretty(&package_json)?;
    std::fs::write(path, format!("{text}\n"))
        .with_context(|| format!("Writing {}", path.display()))?;
    Ok(())
}

pub(crate) fn has_local_file_dependencies(dependencies: &[PackageDependency]) -> bool {
    dependencies
        .iter()
        .any(|dep| matches!(dep.kind, PackageDependencyKind::LocalFile { .. }))
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

    let specifier = if raw_value.starts_with("npm:") || raw_value.starts_with("jsr:") {
        raw_value.to_string()
    } else {
        format!("npm:{alias}@{raw_value}")
    };
    if !specifier.starts_with("npm:") && !specifier.starts_with("jsr:") {
        bail!(
            "Belgie dependency '{alias}' must use an npm:, jsr:, or file: specifier, got '{raw_value}'"
        );
    }
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

fn relative_path(from: &Path, to: &Path) -> PathBuf {
    let from_components = components_without_cur_dir(from);
    let to_components = components_without_cur_dir(to);
    if from_components.first() != to_components.first() {
        return to.to_path_buf();
    }

    let common = from_components
        .iter()
        .zip(&to_components)
        .take_while(|(left, right)| left == right)
        .count();
    let mut relative = PathBuf::new();
    for _ in from_components[common..]
        .iter()
        .filter(|component| matches!(component, Component::Normal(_)))
    {
        relative.push("..");
    }
    for component in &to_components[common..] {
        relative.push(component.as_os_str());
    }
    if relative.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        relative
    }
}

fn components_without_cur_dir(path: &Path) -> Vec<Component<'_>> {
    path.components()
        .filter(|component| !matches!(component, Component::CurDir))
        .collect()
}

fn path_for_package_json(path: PathBuf) -> String {
    let text = path.to_string_lossy();
    if std::path::MAIN_SEPARATOR == '/' {
        text.into_owned()
    } else {
        text.replace(std::path::MAIN_SEPARATOR, "/")
    }
}

fn read_synthetic_config_imports(
    config_file: &Path,
) -> Result<serde_json::Map<String, serde_json::Value>, AnyError> {
    let text = std::fs::read_to_string(config_file)
        .with_context(|| format!("Reading {}", config_file.display()))?;
    let config: serde_json::Value = serde_json::from_str(&text)
        .with_context(|| format!("Parsing {}", config_file.display()))?;
    config
        .get("imports")
        .and_then(|value| value.as_object())
        .cloned()
        .ok_or_else(|| {
            deno_core::anyhow::anyhow!("Synthetic belgie Deno config is missing an imports table")
        })
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
        let workspace = Path::new("/project");
        let dep =
            normalize_dependency(workspace, "local-pkg", "file:./packages/local-pkg").unwrap();

        assert_eq!(dep.alias, "local-pkg");
        assert_eq!(
            dep.kind,
            PackageDependencyKind::LocalFile {
                target_path: PathBuf::from("/project/packages/local-pkg")
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
    fn synthetic_config_uses_manual_node_modules_for_file_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        let config_path = temp_dir.path().join("deno.json");
        let dependencies = vec![
            normalize_dependency(temp_dir.path(), "react", "^19").unwrap(),
            normalize_dependency(temp_dir.path(), "local-pkg", "file:./local-pkg").unwrap(),
        ];

        write_synthetic_config(&config_path, &dependencies).unwrap();

        let text = fs::read_to_string(config_path).unwrap();
        let config: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(config["imports"]["react"], "npm:react@^19");
        assert!(config["imports"].get("local-pkg").is_none());
        assert_eq!(config["nodeModulesDir"], "manual");
    }

    #[test]
    fn synthetic_package_json_contains_file_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        fs::create_dir_all(&workspace).unwrap();
        fs::create_dir_all(&install_root).unwrap();
        let package_json_path = install_root.join("package.json");
        let dependencies = vec![
            normalize_dependency(&workspace, "react", "^19").unwrap(),
            normalize_dependency(&workspace, "local-pkg", "file:./local-pkg").unwrap(),
        ];

        write_synthetic_package_json(&package_json_path, &install_root, &dependencies).unwrap();

        let text = fs::read_to_string(package_json_path).unwrap();
        let package_json: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(
            package_json["dependencies"]["local-pkg"],
            format!(
                "file:{}",
                path_for_package_json(relative_path(&install_root, &workspace.join("local-pkg")))
            )
        );
        assert!(package_json["dependencies"].get("react").is_none());
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
