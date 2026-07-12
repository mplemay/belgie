use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use deno_core::anyhow::{Context, anyhow, bail};
use deno_core::error::AnyError;
use deno_core::serde_json;
use deno_core::url::Url;
use deno_graph::ModuleSpecifier;
use deno_npm_cache::{hard_link_file, is_etxtbsy};
use deno_package_json::{PackageJson, PackageJsonDepValue};
use deno_resolver::workspace::SpecifiedImportMap;

use crate::embed::EmbedContextOptions;
use crate::embed::sys::EmbedSys;
use crate::utils::symlink::remove_symlink_if_present;

pub(crate) const EMPTY_DENO_LOCK: &str = "{\"version\":\"5\"}\n";
pub(crate) const BELGIE_DIR: &str = ".belgie";
const LOCAL_FILE_DEPS_STATE: &str = "local-file-deps.json";
const LOCAL_PACKAGE_MARKER: &str = ".belgie-local-package";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PackageDependency {
    alias: String,
    kind: PackageDependencyKind,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct DependencyLayout {
    pub has_local: bool,
    pub has_registry: bool,
    pub manual_node_modules: bool,
}

impl DependencyLayout {
    pub(crate) fn from_dependencies(dependencies: &[PackageDependency]) -> Self {
        let mut has_local = false;
        let mut has_registry = false;
        for dep in dependencies {
            match &dep.kind {
                PackageDependencyKind::ImportMap { .. } => has_registry = true,
                PackageDependencyKind::LocalFile { .. } => has_local = true,
            }
        }
        Self {
            has_local,
            has_registry,
            manual_node_modules: has_local && !has_registry,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum PackageDependencyKind {
    ImportMap {
        specifier: String,
    },
    LocalFile {
        target_path: PathBuf,
        entrypoint: PathBuf,
    },
}

impl PackageDependency {
    pub(crate) fn alias(&self) -> &str {
        &self.alias
    }

    pub(crate) fn registry_specifier(&self) -> Option<&str> {
        match &self.kind {
            PackageDependencyKind::ImportMap { specifier } => Some(specifier),
            PackageDependencyKind::LocalFile { .. } => None,
        }
    }

    pub(crate) fn set_registry_specifier(&mut self, specifier: String) {
        let PackageDependencyKind::ImportMap { specifier: current } = &mut self.kind else {
            return;
        };
        *current = specifier;
    }
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
    pub dependencies: Vec<PackageDependency>,
}

#[derive(Clone, Debug)]
pub(crate) struct EnvironmentUpdateChange {
    pub name: String,
    pub previous: String,
    pub updated: String,
}

pub(crate) struct EnvironmentUpdateRequest {
    pub cwd: PathBuf,
    pub lockfile: PathBuf,
    pub dependencies: Vec<PackageDependency>,
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

pub(crate) fn is_registry_import_specifier(specifier: &str) -> bool {
    specifier.starts_with("npm:") || specifier.starts_with("jsr:")
}

pub(crate) fn is_resolver_import_specifier(specifier: &str) -> bool {
    ModuleSpecifier::parse(specifier)
        .ok()
        .is_some_and(|url| matches!(url.scheme(), "npm" | "jsr" | "http" | "https"))
}

pub(crate) fn import_map_value(
    dependencies: &[PackageDependency],
) -> Result<serde_json::Value, AnyError> {
    Ok(serde_json::json!({
        "imports": dependency_imports(dependencies)?,
    }))
}

pub(crate) fn specified_import_map(
    base_url: Url,
    dependencies: &[PackageDependency],
) -> Result<SpecifiedImportMap, AnyError> {
    Ok(SpecifiedImportMap {
        base_url,
        value: import_map_value(dependencies)?,
    })
}

pub(crate) fn refresh_specified_import_map(
    options: &mut EmbedContextOptions,
    dependencies: &[PackageDependency],
) -> Result<(), AnyError> {
    if let Some(import_map) = &mut options.specified_import_map {
        import_map.value = import_map_value(dependencies)?;
    }
    Ok(())
}

pub(crate) fn registry_imports(
    dependencies: &[PackageDependency],
) -> serde_json::Map<String, serde_json::Value> {
    dependencies
        .iter()
        .filter_map(|dep| {
            dep.registry_specifier().map(|specifier| {
                (
                    dep.alias.clone(),
                    serde_json::Value::String(specifier.to_string()),
                )
            })
        })
        .collect()
}

fn dependency_imports(
    dependencies: &[PackageDependency],
) -> Result<BTreeMap<String, String>, AnyError> {
    let mut imports = BTreeMap::new();
    for dep in dependencies {
        match &dep.kind {
            PackageDependencyKind::ImportMap { specifier } => {
                imports.insert(dep.alias.clone(), specifier.clone());
                // Deno import maps need a trailing-slash prefix for subpath imports
                // (e.g. `@belgie/mcp/manifest` → `npm:@belgie/mcp@0.1.0/manifest`).
                imports.insert(
                    format!("{}/", dep.alias),
                    format!("{}/", specifier.trim_end_matches('/')),
                );
            }
            PackageDependencyKind::LocalFile {
                target_path,
                entrypoint,
            } => {
                let entrypoint_rel = entrypoint.strip_prefix(target_path).with_context(|| {
                    format!(
                        "Entrypoint {} is not under package root {}",
                        entrypoint.display(),
                        target_path.display()
                    )
                })?;
                let entrypoint_path = posix_relative_path(entrypoint_rel);
                imports.insert(
                    dep.alias.clone(),
                    format!("./node_modules/{}/{}", dep.alias, entrypoint_path),
                );
                for (subpath, file_path) in local_file_export_subpaths(target_path)? {
                    imports.insert(
                        format!("{}{}", dep.alias, subpath),
                        format!("./node_modules/{}/{}", dep.alias, file_path),
                    );
                }
                imports.insert(
                    format!("{}/", dep.alias),
                    format!("./node_modules/{}/", dep.alias),
                );
            }
        }
    }
    Ok(imports)
}

fn local_file_export_subpaths(target_path: &Path) -> Result<Vec<(String, String)>, AnyError> {
    let package_json_path = target_path.join("package.json");
    if !package_json_path.is_file() {
        return Ok(Vec::new());
    }
    let sys = EmbedSys::default();
    let Some(package_json) =
        PackageJson::load_from_path(&sys, None, &package_json_path).map_err(AnyError::from)?
    else {
        return Ok(Vec::new());
    };
    let Some(exports) = package_json.exports.as_ref() else {
        return Ok(Vec::new());
    };

    let mut subpaths = Vec::new();
    for (key, value) in exports {
        if key == "." {
            continue;
        }
        let Some(entrypoint) = package_export_entrypoint(value) else {
            continue;
        };
        let subpath = if let Some(rest) = key.strip_prefix("./") {
            format!("/{rest}")
        } else if let Some(rest) = key.strip_prefix('/') {
            format!("/{rest}")
        } else {
            format!("/{key}")
        };
        let file_path = entrypoint
            .strip_prefix("./")
            .unwrap_or(entrypoint)
            .to_string();
        subpaths.push((subpath, file_path));
    }
    Ok(subpaths)
}

pub(crate) fn local_file_dependency_install_roots(
    dependencies: &[PackageDependency],
) -> Result<Vec<ModuleSpecifier>, AnyError> {
    let mut roots = Vec::new();
    for dep in dependencies {
        let PackageDependencyKind::LocalFile {
            target_path,
            entrypoint,
        } = &dep.kind
        else {
            continue;
        };
        let registry_roots = local_package_registry_roots(target_path)?;
        if registry_roots.is_empty() {
            let url = deno_path_util::url_from_file_path(entrypoint).map_err(|error| {
                anyhow!(
                    "Could not convert local package entrypoint {} to a file URL: {error}",
                    entrypoint.display()
                )
            })?;
            roots.push(ModuleSpecifier::from(url));
            continue;
        }
        roots.extend(registry_roots);
    }
    Ok(roots)
}

fn local_package_registry_roots(target_path: &Path) -> Result<Vec<ModuleSpecifier>, AnyError> {
    let package_json_path = target_path.join("package.json");
    if !package_json_path.is_file() {
        return Ok(Vec::new());
    }
    let sys = EmbedSys::default();
    let Some(package_json) =
        PackageJson::load_from_path(&sys, None, &package_json_path).map_err(AnyError::from)?
    else {
        return Ok(Vec::new());
    };
    let mut roots = Vec::new();
    let Some(deps) = package_json.dependencies.as_ref() else {
        return Ok(roots);
    };
    for (name, value) in deps {
        let specifier = if is_registry_import_specifier(value) {
            value.clone()
        } else {
            match PackageJsonDepValue::parse(name, value) {
                Ok(PackageJsonDepValue::Req(req)) => format!("npm:{req}"),
                _ => continue,
            }
        };
        let Ok(root) = ModuleSpecifier::parse(&specifier) else {
            continue;
        };
        roots.push(root);
    }
    Ok(roots)
}

fn posix_relative_path(path: &Path) -> String {
    path.components()
        .map(|component| component.as_os_str().to_string_lossy())
        .collect::<Vec<_>>()
        .join("/")
}

fn local_file_dependency_entrypoint(target_path: &Path) -> Result<PathBuf, AnyError> {
    let package_json_path = target_path.join("package.json");
    if !package_json_path.is_file() {
        return Ok(target_path.join("index.js"));
    }
    let sys = EmbedSys::default();
    let Some(package_json) =
        PackageJson::load_from_path(&sys, None, &package_json_path).map_err(AnyError::from)?
    else {
        return Ok(target_path.join("index.js"));
    };
    let entrypoint = package_json
        .exports
        .as_ref()
        .map(|exports| serde_json::Value::Object(exports.clone()))
        .and_then(|exports| package_export_entrypoint(&exports).map(str::to_string))
        .or(package_json.module.clone())
        .or(package_json.main.clone())
        .unwrap_or_else(|| "index.js".to_string());
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

pub(crate) fn has_legacy_local_file_state(install_root: &Path) -> bool {
    install_root.join(BELGIE_DIR).is_dir()
}

pub(crate) fn sync_local_file_dependencies(
    install_root: &Path,
    node_modules_root: &Path,
    dependencies: &[PackageDependency],
) -> Result<(), AnyError> {
    remove_legacy_synthetic_package_json(&install_root.join("package.json"))?;

    let current = local_file_dependencies(dependencies);
    let previous = read_owned_local_file_aliases(install_root, node_modules_root, &current)?;

    for alias in &previous {
        if current.contains_key(alias) {
            continue;
        }
        remove_installed_local_package(&node_modules_root.join(alias))?;
    }

    if current.is_empty() {
        remove_legacy_local_file_state(install_root)?;
        return Ok(());
    }

    std::fs::create_dir_all(node_modules_root)
        .with_context(|| format!("Creating {}", node_modules_root.display()))?;
    for (alias, target_path) in &current {
        let dest = node_modules_root.join(alias);
        if local_package_needs_sync(target_path, &dest)? {
            remove_installed_local_package(&dest)?;
            materialize_local_package(target_path, &dest)?;
        }
    }
    remove_legacy_local_file_state(install_root)
}

pub(crate) async fn install_environment_packages(
    cwd: PathBuf,
    lockfile: PathBuf,
    lockfile_only: bool,
    options: EmbedContextOptions,
) -> Result<PathBuf, AnyError> {
    crate::embed::install_packages_with_options(cwd, lockfile.clone(), lockfile_only, options)
        .await?;
    Ok(lockfile)
}

pub(crate) async fn update_environment_packages(
    request: EnvironmentUpdateRequest,
) -> Result<EnvironmentUpdateResult, AnyError> {
    if request.dependencies.is_empty() {
        return Ok(EnvironmentUpdateResult {
            lockfile: request.lockfile,
            changes: Vec::new(),
            dependencies: request.dependencies,
        });
    }

    let before = registry_imports(&request.dependencies);
    let updated_dependencies = crate::embed::update_packages(
        request.cwd,
        request.lockfile.clone(),
        request.packages,
        request.latest,
        request.lockfile_only,
        request.options,
        request.dependencies,
    )
    .await?;
    let after = registry_imports(&updated_dependencies);

    Ok(EnvironmentUpdateResult {
        lockfile: request.lockfile,
        changes: update_changes_from_imports(&before, &after),
        dependencies: updated_dependencies,
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
        let target_path = normalize_workspace_path(workspace, path)?;
        return Ok(PackageDependency {
            alias: alias.to_string(),
            kind: PackageDependencyKind::LocalFile {
                target_path: target_path.clone(),
                entrypoint: local_file_dependency_entrypoint(&target_path)?,
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
            let PackageDependencyKind::LocalFile { target_path, .. } = &dep.kind else {
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

fn read_owned_local_file_aliases(
    install_root: &Path,
    node_modules_root: &Path,
    current: &BTreeMap<String, PathBuf>,
) -> Result<Vec<String>, AnyError> {
    let mut aliases = read_tracked_local_file_aliases(install_root)?
        .into_iter()
        .collect::<BTreeSet<_>>();
    if current.is_empty()
        && aliases.is_empty()
        && !local_file_deps_state_path(install_root).is_file()
        && (!node_modules_root.is_dir()
            || std::fs::read_dir(node_modules_root)
                .with_context(|| format!("Reading {}", node_modules_root.display()))?
                .next()
                .transpose()?
                .is_none())
    {
        return Ok(Vec::new());
    }
    aliases.extend(read_marked_local_file_aliases(node_modules_root)?);
    Ok(aliases.into_iter().collect())
}

fn read_marked_local_file_aliases(node_modules_root: &Path) -> Result<Vec<String>, AnyError> {
    if !node_modules_root.is_dir() {
        return Ok(Vec::new());
    }
    let mut aliases = Vec::new();
    for entry in std::fs::read_dir(node_modules_root)
        .with_context(|| format!("Reading {}", node_modules_root.display()))?
    {
        let entry = entry.with_context(|| format!("Reading {}", node_modules_root.display()))?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let path = entry.path();
        if name.starts_with('@') && path.is_dir() {
            aliases.extend(read_marked_scoped_local_file_aliases(&name, &path)?);
        } else if path.join(LOCAL_PACKAGE_MARKER).is_file() {
            aliases.push(name);
        }
    }
    Ok(aliases)
}

fn read_marked_scoped_local_file_aliases(
    scope: &str,
    scope_root: &Path,
) -> Result<Vec<String>, AnyError> {
    let mut aliases = Vec::new();
    for entry in std::fs::read_dir(scope_root)
        .with_context(|| format!("Reading {}", scope_root.display()))?
    {
        let entry = entry.with_context(|| format!("Reading {}", scope_root.display()))?;
        let package_path = entry.path();
        if package_path.join(LOCAL_PACKAGE_MARKER).is_file() {
            aliases.push(format!("{scope}/{}", entry.file_name().to_string_lossy()));
        }
    }
    Ok(aliases)
}

fn remove_legacy_local_file_state(install_root: &Path) -> Result<(), AnyError> {
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

const SKIP_LOCAL_PACKAGE_ENTRIES: &[&str] =
    &["node_modules", ".deno", ".git", LOCAL_PACKAGE_MARKER];

fn local_package_needs_sync(source: &Path, dest: &Path) -> Result<bool, AnyError> {
    if !dest.exists() {
        return Ok(true);
    }
    if !dest.join(LOCAL_PACKAGE_MARKER).is_file() {
        return Ok(true);
    }
    let source_modified = dir_modified_time(source)?;
    let dest_modified = dir_modified_time(dest)?;
    Ok(source_modified > dest_modified)
}

fn dir_modified_time(path: &Path) -> Result<SystemTime, AnyError> {
    std::fs::metadata(path)
        .and_then(|metadata| metadata.modified())
        .with_context(|| format!("Reading metadata for {}", path.display()))
}

fn materialize_local_package(source: &Path, dest: &Path) -> Result<(), AnyError> {
    let _ = std::fs::remove_dir_all(dest);
    std::fs::create_dir_all(dest).with_context(|| format!("Creating {}", dest.display()))?;
    materialize_local_package_entries(&EmbedSys::default(), source, dest)?;
    std::fs::write(
        dest.join(LOCAL_PACKAGE_MARKER),
        "belgie local file dependency\n",
    )
    .with_context(|| format!("Writing {}", dest.join(LOCAL_PACKAGE_MARKER).display()))
}

fn materialize_local_package_entries(
    sys: &EmbedSys,
    source: &Path,
    dest: &Path,
) -> Result<(), AnyError> {
    for entry in
        std::fs::read_dir(source).with_context(|| format!("Reading {}", source.display()))?
    {
        let entry = entry.with_context(|| format!("Reading {}", source.display()))?;
        let file_name = entry.file_name();
        let file_name = file_name.to_string_lossy();
        if SKIP_LOCAL_PACKAGE_ENTRIES.contains(&file_name.as_ref()) {
            continue;
        }
        let file_type = entry
            .file_type()
            .with_context(|| format!("Reading metadata for {}", entry.path().display()))?;
        if file_type.is_symlink() {
            continue;
        }
        let new_from = source.join(entry.file_name());
        let new_to = dest.join(entry.file_name());
        if file_type.is_dir() {
            std::fs::create_dir_all(&new_to)
                .with_context(|| format!("Creating {}", new_to.display()))?;
            materialize_local_package_entries(sys, &new_from, &new_to)?;
        } else if file_type.is_file() {
            materialize_local_package_file(sys, &new_from, &new_to)?;
        }
    }
    Ok(())
}

fn materialize_local_package_file(sys: &EmbedSys, from: &Path, to: &Path) -> Result<(), AnyError> {
    if hard_link_file(sys, from, to).is_err() {
        std::fs::copy(from, to)
            .or_else(|error| {
                if is_etxtbsy(&error) {
                    let _ = std::fs::remove_file(to);
                    std::fs::copy(from, to)
                } else {
                    Err(error)
                }
            })
            .with_context(|| format!("Copying {} to {}", from.display(), to.display()))?;
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
    fn classifies_resolver_import_specifiers() {
        assert!(is_resolver_import_specifier("jsr:@std/path@1"));
        assert!(is_resolver_import_specifier("npm:is-number@7.0.0"));
        assert!(is_resolver_import_specifier("https://example.com/mod.ts"));
        assert!(is_resolver_import_specifier("http://example.com/mod.ts"));
        assert!(!is_resolver_import_specifier("node:fs"));
        assert!(!is_resolver_import_specifier("./mod.ts"));
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
                target_path: expected.clone(),
                entrypoint: expected.join("index.js"),
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
    fn import_map_contains_registry_imports() {
        let temp_dir = tempfile::tempdir().unwrap();
        let dependencies = vec![
            normalize_dependency(temp_dir.path(), "react", "^19").unwrap(),
            normalize_dependency(temp_dir.path(), "@belgie/mcp", "npm:@belgie/mcp@0.1.0").unwrap(),
        ];

        let import_map = import_map_value(&dependencies).unwrap();

        assert_eq!(import_map["imports"]["react"], "npm:react@^19");
        assert_eq!(import_map["imports"]["react/"], "npm:react@^19/");
        assert_eq!(
            import_map["imports"]["@belgie/mcp"],
            "npm:@belgie/mcp@0.1.0"
        );
        assert_eq!(
            import_map["imports"]["@belgie/mcp/"],
            "npm:@belgie/mcp@0.1.0/"
        );
    }

    #[test]
    fn import_map_contains_file_dependency_imports() {
        let temp_dir = tempfile::tempdir().unwrap();
        let dependencies =
            vec![normalize_dependency(temp_dir.path(), "local-pkg", "file:./local-pkg").unwrap()];

        let import_map = import_map_value(&dependencies).unwrap();

        assert_eq!(
            import_map["imports"]["local-pkg"],
            "./node_modules/local-pkg/index.js"
        );
        assert_eq!(
            import_map["imports"]["local-pkg/"],
            "./node_modules/local-pkg/"
        );
    }

    #[test]
    fn import_map_contains_file_dependency_export_subpaths() {
        let temp_dir = tempfile::tempdir().unwrap();
        let local_pkg = temp_dir.path().join("local-pkg");
        std::fs::create_dir_all(local_pkg.join("dist")).unwrap();
        std::fs::write(
            local_pkg.join("package.json"),
            r#"{
  "name": "local-pkg",
  "version": "1.0.0",
  "type": "module",
  "exports": {
    ".": {
      "import": "./dist/index.js"
    },
    "./manifest": {
      "import": "./dist/manifest.js"
    },
    "./vite": {
      "import": "./dist/vite.js"
    }
  }
}
"#,
        )
        .unwrap();
        std::fs::write(local_pkg.join("dist").join("index.js"), "export {};\n").unwrap();
        let dependencies =
            vec![normalize_dependency(temp_dir.path(), "@belgie/mcp", "file:./local-pkg").unwrap()];

        let import_map = import_map_value(&dependencies).unwrap();

        assert_eq!(
            import_map["imports"]["@belgie/mcp"],
            "./node_modules/@belgie/mcp/dist/index.js"
        );
        assert_eq!(
            import_map["imports"]["@belgie/mcp/manifest"],
            "./node_modules/@belgie/mcp/dist/manifest.js"
        );
        assert_eq!(
            import_map["imports"]["@belgie/mcp/vite"],
            "./node_modules/@belgie/mcp/dist/vite.js"
        );
        assert_eq!(
            import_map["imports"]["@belgie/mcp/"],
            "./node_modules/@belgie/mcp/"
        );
    }

    #[test]
    fn local_file_dependency_install_roots_include_package_json_registry_deps() {
        let temp_dir = tempfile::tempdir().unwrap();
        let local_pkg = temp_dir.path().join("local-pkg");
        std::fs::create_dir_all(&local_pkg).unwrap();
        std::fs::write(
            local_pkg.join("package.json"),
            r#"{
  "name": "local-pkg",
  "version": "1.0.0",
  "dependencies": {
    "is-number": "7.0.0"
  }
}
"#,
        )
        .unwrap();
        std::fs::write(local_pkg.join("index.js"), "export const answer = 42;\n").unwrap();
        let dependencies =
            vec![normalize_dependency(temp_dir.path(), "local-pkg", "file:./local-pkg").unwrap()];

        let roots = local_file_dependency_install_roots(&dependencies).unwrap();

        assert_eq!(roots.len(), 1);
        assert_eq!(roots[0].as_str(), "npm:is-number@7.0.0");
    }

    #[test]
    fn import_map_contains_mixed_file_and_registry_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        let dependencies = vec![
            normalize_dependency(temp_dir.path(), "react", "^19").unwrap(),
            normalize_dependency(temp_dir.path(), "local-pkg", "file:./local-pkg").unwrap(),
        ];

        let import_map = import_map_value(&dependencies).unwrap();

        assert_eq!(import_map["imports"]["react"], "npm:react@^19");
        assert_eq!(
            import_map["imports"]["local-pkg"],
            "./node_modules/local-pkg/index.js"
        );
        assert_eq!(
            import_map["imports"]["local-pkg/"],
            "./node_modules/local-pkg/"
        );
    }

    #[test]
    fn sync_local_file_dependencies_creates_package_copy() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let local_pkg = workspace.join("local-pkg");
        fs::create_dir_all(&local_pkg).unwrap();
        fs::write(local_pkg.join("index.js"), "export const answer = 42;\n").unwrap();
        let node_modules = install_root.join("node_modules");
        let dependencies =
            vec![normalize_dependency(&workspace, "local-pkg", "file:./local-pkg").unwrap()];

        sync_local_file_dependencies(&install_root, &node_modules, &dependencies).unwrap();

        let installed = node_modules.join("local-pkg");
        assert!(installed.is_dir());
        assert!(!installed.is_symlink());
        assert_eq!(
            fs::read_to_string(installed.join("index.js")).unwrap(),
            "export const answer = 42;\n"
        );
        assert!(!install_root.join("package.json").exists());
        assert!(installed.join(LOCAL_PACKAGE_MARKER).is_file());
        assert!(!install_root.join(BELGIE_DIR).exists());
    }

    #[test]
    fn sync_local_file_dependencies_creates_scoped_package_copy() {
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

        sync_local_file_dependencies(&install_root, &node_modules, &dependencies).unwrap();

        let installed = node_modules.join("@scope").join("pkg");
        assert!(installed.is_dir());
        assert!(!installed.is_symlink());
        assert_eq!(
            fs::read_to_string(installed.join("index.js")).unwrap(),
            "export const answer = 42;\n"
        );
    }

    #[test]
    fn sync_local_file_dependencies_skips_nested_dependency_dirs() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let local_pkg = workspace.join("local-pkg");
        fs::create_dir_all(local_pkg.join("node_modules").join("dep")).unwrap();
        fs::create_dir_all(local_pkg.join(".deno").join("dep")).unwrap();
        fs::create_dir_all(local_pkg.join(".git")).unwrap();
        fs::write(local_pkg.join("index.js"), "export const answer = 42;\n").unwrap();
        fs::write(
            local_pkg.join("node_modules").join("dep").join("index.js"),
            "export const nested = true;\n",
        )
        .unwrap();
        fs::write(
            local_pkg.join(".deno").join("dep").join("index.js"),
            "export const deno = true;\n",
        )
        .unwrap();
        fs::write(local_pkg.join(".git").join("config"), "[core]\n").unwrap();
        let node_modules = install_root.join("node_modules");
        let dependencies =
            vec![normalize_dependency(&workspace, "local-pkg", "file:./local-pkg").unwrap()];

        sync_local_file_dependencies(&install_root, &node_modules, &dependencies).unwrap();

        let installed = node_modules.join("local-pkg");
        assert!(installed.join("index.js").is_file());
        assert!(!installed.join("node_modules").exists());
        assert!(!installed.join(".deno").exists());
        assert!(!installed.join(".git").exists());
    }

    #[cfg(unix)]
    #[test]
    fn sync_local_file_dependencies_skips_symlink_entries() {
        use std::os::unix::fs::symlink;

        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let local_pkg = workspace.join("local-pkg");
        fs::create_dir_all(&local_pkg).unwrap();
        fs::write(local_pkg.join("index.js"), "export const answer = 42;\n").unwrap();
        let symlink_target = workspace.join("shared.js");
        fs::write(&symlink_target, "export const shared = true;\n").unwrap();
        symlink(&symlink_target, local_pkg.join("shared.js")).unwrap();
        let node_modules = install_root.join("node_modules");
        let dependencies =
            vec![normalize_dependency(&workspace, "local-pkg", "file:./local-pkg").unwrap()];

        sync_local_file_dependencies(&install_root, &node_modules, &dependencies).unwrap();

        let installed = node_modules.join("local-pkg");
        assert!(installed.join("index.js").is_file());
        assert!(!installed.join("shared.js").exists());
    }

    #[test]
    fn sync_local_file_dependencies_removes_stale_alias() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let local_pkg = workspace.join("local-pkg");
        fs::create_dir_all(&local_pkg).unwrap();
        let node_modules = install_root.join("node_modules");
        let file_dependencies =
            vec![normalize_dependency(&workspace, "local-pkg", "file:./local-pkg").unwrap()];
        sync_local_file_dependencies(&install_root, &node_modules, &file_dependencies).unwrap();

        let npm_dependencies = vec![normalize_dependency(&workspace, "react", "^19").unwrap()];
        sync_local_file_dependencies(&install_root, &node_modules, &npm_dependencies).unwrap();

        assert!(!node_modules.join("local-pkg").exists());
        assert!(!install_root.join(BELGIE_DIR).exists());
    }

    #[test]
    fn sync_local_file_dependencies_removes_legacy_tracked_aliases() {
        let temp_dir = tempfile::tempdir().unwrap();
        let workspace = temp_dir.path().join("workspace");
        let install_root = temp_dir.path().join("install");
        let node_modules = install_root.join("node_modules");
        let installed = node_modules.join("local-pkg");
        fs::create_dir_all(&installed).unwrap();
        fs::create_dir_all(install_root.join(BELGIE_DIR)).unwrap();
        fs::write(
            install_root.join(BELGIE_DIR).join(LOCAL_FILE_DEPS_STATE),
            "[\"local-pkg\"]\n",
        )
        .unwrap();

        let npm_dependencies = vec![normalize_dependency(&workspace, "react", "^19").unwrap()];
        sync_local_file_dependencies(&install_root, &node_modules, &npm_dependencies).unwrap();

        assert!(!installed.exists());
        assert!(!install_root.join(BELGIE_DIR).exists());
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
