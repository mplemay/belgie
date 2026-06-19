use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use deno_core::anyhow::{Context, bail};
use deno_core::error::AnyError;
use deno_core::serde_json;

use crate::embed::EmbedContextOptions;

pub(crate) const EMPTY_DENO_LOCK: &str = "{\"version\":\"5\"}\n";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PackageDependency {
    alias: String,
    specifier: String,
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
    dependencies: BTreeMap<String, String>,
) -> Result<Vec<PackageDependency>, AnyError> {
    dependencies
        .into_iter()
        .map(|(alias, specifier)| normalize_dependency(&alias, &specifier))
        .collect()
}

pub(crate) fn write_synthetic_config(
    path: &Path,
    dependencies: &[PackageDependency],
) -> Result<(), AnyError> {
    let imports = dependencies
        .iter()
        .map(|dep| (dep.alias.clone(), dep.specifier.clone()))
        .collect::<BTreeMap<_, _>>();
    let config = serde_json::json!({
      "imports": imports,
      "nodeModulesDir": "auto",
    });
    let text = serde_json::to_string_pretty(&config)?;
    std::fs::write(path, format!("{text}\n"))
        .with_context(|| format!("Writing {}", path.display()))?;
    Ok(())
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

fn normalize_dependency(alias: &str, raw_value: &str) -> Result<PackageDependency, AnyError> {
    let specifier = if raw_value.starts_with("npm:") || raw_value.starts_with("jsr:") {
        raw_value.to_string()
    } else {
        format!("npm:{alias}@{raw_value}")
    };
    if !specifier.starts_with("npm:") && !specifier.starts_with("jsr:") {
        bail!("Belgie dependency '{alias}' must use an npm: or jsr: specifier, got '{raw_value}'");
    }
    Ok(PackageDependency {
        alias: alias.to_string(),
        specifier,
    })
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
        let dep = normalize_dependency("react", "^19").unwrap();

        assert_eq!(dep.alias, "react");
        assert_eq!(dep.specifier, "npm:react@^19");
    }

    #[test]
    fn preserves_explicit_jsr_specifiers() {
        let dep = normalize_dependency("@std/path", "jsr:@std/path@^1").unwrap();

        assert_eq!(dep.specifier, "jsr:@std/path@^1");
    }

    #[test]
    fn synthetic_config_contains_imports_and_enables_isolated_node_modules_dir() {
        let temp_dir = tempfile::tempdir().unwrap();
        let config_path = temp_dir.path().join("deno.json");
        let dependencies = vec![normalize_dependency("react", "^19").unwrap()];

        write_synthetic_config(&config_path, &dependencies).unwrap();

        let text = fs::read_to_string(config_path).unwrap();
        let config: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(config["imports"]["react"], "npm:react@^19");
        assert_eq!(config["nodeModulesDir"], "auto");
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
