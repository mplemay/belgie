use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use deno_core::anyhow::{Context, anyhow, bail};
use deno_core::error::AnyError;
use deno_core::serde_json;
use tempfile::TempDir;
use toml_edit::{DocumentMut, value};

use crate::embed::{EmbedContext, EmbedContextOptions};

const DEFAULT_GROUP: &str = "default";
pub(crate) const EMPTY_DENO_LOCK: &str = "{\"version\":\"5\"}\n";

#[derive(Clone, Debug, Eq, PartialEq)]
enum PyprojectValueKind {
    VersionOnly,
    FullSpecifier,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PackageDependency {
    alias: String,
    specifier: String,
    group: String,
    value_kind: PyprojectValueKind,
}

#[derive(Clone, Debug)]
pub(crate) struct PackageEnvironment {
    inner: Rc<PackageEnvironmentInner>,
}

#[derive(Debug)]
struct PackageEnvironmentInner {
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    dependencies: Vec<PackageDependency>,
    embed_options: EmbedContextOptions,
    embed_context: Mutex<Option<Rc<EmbedContext>>>,
    temp_dir: TempDir,
}

#[derive(Clone, Debug)]
pub(crate) struct ProjectPackageEnvironment {
    inner: Arc<ProjectPackageEnvironmentInner>,
}

#[derive(Debug)]
struct ProjectPackageEnvironmentInner {
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    embed_options: EmbedContextOptions,
    temp_dir: TempDir,
}

#[derive(Clone, Debug)]
pub(crate) struct PackageInstallResult {
    pub lockfile: PathBuf,
    pub groups: BTreeMap<String, usize>,
}

#[derive(Clone, Debug)]
pub(crate) struct PackageUpdateResult {
    pub lockfile: PathBuf,
    pub changes: Vec<PackageUpdateChange>,
}

#[derive(Clone, Debug)]
pub(crate) struct PackageUpdateChange {
    pub name: String,
    pub previous: String,
    pub updated: String,
}

#[derive(Debug)]
struct PyprojectManifest {
    path: PathBuf,
    document: DocumentMut,
    dependencies: Vec<PackageDependency>,
    scripts: BTreeMap<String, String>,
}

impl PackageEnvironment {
    fn required(
        cwd: PathBuf,
        groups: Option<Vec<String>>,
        embed_options: EmbedContextOptions,
    ) -> Result<Self, AnyError> {
        let Some(manifest) = read_manifest(&cwd, groups.clone())? else {
            return Err(no_dependencies_error(&cwd, groups));
        };
        if manifest.dependencies.is_empty() {
            return Err(no_dependencies_error(&cwd, groups));
        }
        Self::from_manifest_parts(cwd, manifest.dependencies, embed_options)
    }

    #[cfg(test)]
    fn from_dependencies(
        cwd: PathBuf,
        dependencies: Vec<PackageDependency>,
    ) -> Result<Self, AnyError> {
        Self::from_manifest_parts(cwd, dependencies, EmbedContextOptions::default())
    }

    fn from_manifest_parts(
        cwd: PathBuf,
        dependencies: Vec<PackageDependency>,
        embed_options: EmbedContextOptions,
    ) -> Result<Self, AnyError> {
        let temp_dir = tempfile::Builder::new()
            .prefix("belgie-packages-")
            .tempdir()
            .context("Failed to create temporary Deno package config directory")?;
        let config_file = temp_dir.path().join("deno.json");
        write_synthetic_config(&config_file, &dependencies)?;
        let lockfile = cwd.join("deno.lock");
        Ok(Self {
            inner: Rc::new(PackageEnvironmentInner {
                cwd,
                config_file,
                lockfile,
                dependencies,
                embed_options,
                embed_context: Mutex::new(None),
                temp_dir,
            }),
        })
    }

    pub(crate) fn validate_task(
        task_cwd: &Path,
        script_name: &str,
        install: bool,
    ) -> Result<(PathBuf, Vec<PackageDependency>, String), AnyError> {
        let (project_dir, dependencies, command) = resolve_task_manifest(task_cwd, script_name)?;
        validate_project_artifacts(&project_dir, &dependencies, install)?;
        Ok((project_dir, dependencies, command))
    }

    pub(crate) fn resolve_task(
        task_cwd: &Path,
        script_name: &str,
        install: bool,
    ) -> Result<(Self, String), AnyError> {
        let (pyproject_dir, dependencies, command) =
            Self::validate_task(task_cwd, script_name, install)?;
        Self::resolve_task_from_parts(pyproject_dir, dependencies, command, install)
    }

    pub(crate) fn resolve_task_from_parts(
        pyproject_dir: PathBuf,
        dependencies: Vec<PackageDependency>,
        command: String,
        install: bool,
    ) -> Result<(Self, String), AnyError> {
        let options = project_embed_options(&pyproject_dir);
        let env = Self::from_manifest_parts(pyproject_dir, dependencies, options)?;
        if install {
            pyo3_async_runtimes::tokio::get_runtime()
                .block_on(env.synchronize())
                .map_err(project_state_error)?;
        }
        Ok((env, command))
    }

    pub(crate) fn cwd(&self) -> &Path {
        &self.inner.cwd
    }

    pub(crate) fn config_file(&self) -> &Path {
        &self.inner.config_file
    }

    pub(crate) fn lockfile(&self) -> &Path {
        &self.inner.lockfile
    }

    pub(crate) fn dependencies(&self) -> &[PackageDependency] {
        &self.inner.dependencies
    }

    pub(crate) fn embed_paths(&self) -> (PathBuf, PathBuf, PathBuf) {
        (
            self.cwd().to_path_buf(),
            self.config_file().to_path_buf(),
            self.lockfile().to_path_buf(),
        )
    }

    pub(crate) fn embed_context(&self) -> Result<Rc<EmbedContext>, AnyError> {
        let mut guard = self
            .inner
            .embed_context
            .lock()
            .expect("package embed context lock should not be poisoned");
        if guard.is_none() {
            let (cwd, config_file, lockfile) = self.embed_paths();
            *guard = Some(Rc::new(EmbedContext::new_with_options(
                cwd,
                config_file,
                lockfile,
                self.inner.embed_options.clone(),
            )?));
        }
        Ok(guard
            .as_ref()
            .expect("embed context should be initialized")
            .clone())
    }

    pub(crate) async fn synchronize(&self) -> Result<(), AnyError> {
        let (cwd, config_file, lockfile) = self.embed_paths();
        let context =
            synchronize_embed(cwd, config_file, lockfile, self.inner.embed_options.clone()).await?;
        *self
            .inner
            .embed_context
            .lock()
            .expect("package embed context lock should not be poisoned") = Some(context);
        Ok(())
    }

    pub(crate) fn process_state_file(&self) -> PathBuf {
        self.inner.temp_dir.path().join("npm-process-state.json")
    }
}

impl ProjectPackageEnvironment {
    pub(crate) fn from_folder(
        cwd: PathBuf,
        groups: Option<Vec<String>>,
        install: bool,
    ) -> Result<Option<Self>, AnyError> {
        let dependencies = dependencies_from_folder(&cwd, groups)?;
        if dependencies.is_empty() {
            return Ok(None);
        }
        validate_project_artifacts(&cwd, &dependencies, install)?;
        let temp_dir = tempfile::Builder::new()
            .prefix("belgie-project-")
            .tempdir()
            .context("Failed to create temporary Deno project config directory")?;
        let config_file = temp_dir.path().join("deno.json");
        write_synthetic_config(&config_file, &dependencies)?;
        let lockfile = cwd.join("deno.lock");
        let environment = Self {
            inner: Arc::new(ProjectPackageEnvironmentInner {
                embed_options: project_embed_options(&cwd),
                cwd,
                config_file,
                lockfile,
                temp_dir,
            }),
        };
        if install {
            pyo3_async_runtimes::tokio::get_runtime()
                .block_on(environment.synchronize())
                .map_err(project_state_error)?;
        }
        Ok(Some(environment))
    }

    pub(crate) fn embed_context(&self) -> Result<Rc<EmbedContext>, AnyError> {
        debug_assert!(self.inner.temp_dir.path().is_dir());
        Ok(Rc::new(
            EmbedContext::new_with_options(
                self.inner.cwd.clone(),
                self.inner.config_file.clone(),
                self.inner.lockfile.clone(),
                self.inner.embed_options.clone(),
            )
            .map_err(project_state_error)?,
        ))
    }

    async fn synchronize(&self) -> Result<(), AnyError> {
        synchronize_embed(
            self.inner.cwd.clone(),
            self.inner.config_file.clone(),
            self.inner.lockfile.clone(),
            self.inner.embed_options.clone(),
        )
        .await?;
        Ok(())
    }
}

pub(crate) async fn install_packages(
    cwd: PathBuf,
    groups: Option<Vec<String>>,
    lockfile_only: bool,
) -> Result<PackageInstallResult, AnyError> {
    let embed_options = embed_options_for_install(&cwd, lockfile_only);
    let env = PackageEnvironment::required(cwd, groups, embed_options)?;
    let (cwd, config_file, lockfile) = env.embed_paths();
    crate::embed::install_packages_with_options(
        cwd,
        config_file,
        lockfile,
        lockfile_only,
        env.inner.embed_options.clone(),
    )
    .await?;
    Ok(install_result_from_env(&env))
}

pub(crate) async fn lock_packages(
    cwd: PathBuf,
    groups: Option<Vec<String>>,
) -> Result<PackageInstallResult, AnyError> {
    install_packages(cwd, groups, true).await
}

pub(crate) async fn update_packages(
    cwd: PathBuf,
    packages: Vec<String>,
    groups: Option<Vec<String>>,
    latest: bool,
    lockfile_only: bool,
) -> Result<PackageUpdateResult, AnyError> {
    let embed_options = embed_options_for_install(&cwd, lockfile_only);
    let env = PackageEnvironment::required(cwd.clone(), groups, embed_options.clone())?;
    let (project_cwd, config_file, lockfile) = env.embed_paths();
    crate::embed::update_packages(
        project_cwd,
        config_file,
        lockfile,
        packages,
        latest,
        lockfile_only,
        embed_options,
    )
    .await?;

    let changes = if lockfile_only {
        Vec::new()
    } else {
        apply_updates_to_pyproject(&cwd, &env)?
    };
    Ok(PackageUpdateResult {
        lockfile: env.lockfile().to_path_buf(),
        changes,
    })
}

async fn synchronize_embed(
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    options: EmbedContextOptions,
) -> Result<Rc<EmbedContext>, AnyError> {
    crate::embed::install_packages_with_options(cwd, config_file, lockfile, false, options).await
}

fn embed_options_for_install(cwd: &Path, lockfile_only: bool) -> EmbedContextOptions {
    if lockfile_only {
        EmbedContextOptions::default()
    } else {
        local_install_options(cwd)
    }
}

fn local_install_options(cwd: &Path) -> EmbedContextOptions {
    EmbedContextOptions {
        node_modules_root: Some(cwd.join("node_modules")),
        ..Default::default()
    }
}

fn project_embed_options(cwd: &Path) -> EmbedContextOptions {
    EmbedContextOptions {
        frozen_lockfile: Some(true),
        lockfile_skip_write: true,
        ..local_install_options(cwd)
    }
}

fn validate_project_artifacts(
    cwd: &Path,
    dependencies: &[PackageDependency],
    install: bool,
) -> Result<(), AnyError> {
    let lockfile = cwd.join("deno.lock");
    if !lockfile.is_file() {
        bail!(
            "Project dependencies are not installed: missing {}. Run belgie.dependencies.install() before execution.",
            lockfile.display()
        );
    }
    if dependencies.iter().any(PackageDependency::is_npm) && !install {
        let node_modules = cwd.join("node_modules");
        if !node_modules.is_dir() {
            bail!(
                "Project dependencies are not installed: missing {}. Run belgie.dependencies.install() or pass install=True.",
                node_modules.display()
            );
        }
    }
    Ok(())
}

pub(crate) fn project_state_error(error: impl std::fmt::Display) -> AnyError {
    anyhow!(
        "Project dependencies are missing or out of date. Run belgie.dependencies.install() or pass install=True: {error}"
    )
}

fn dependency_tables_have_any_entries(document: &DocumentMut) -> bool {
    document
        .get("belgie")
        .and_then(|belgie| belgie.get("dependencies"))
        .and_then(|deps| deps.as_table())
        .is_some_and(|table| !table.is_empty())
}

fn no_dependencies_error(cwd: &Path, groups: Option<Vec<String>>) -> AnyError {
    let path = cwd.join("pyproject.toml");
    if let Some(group_names) = groups
        && let Ok(text) = std::fs::read_to_string(&path)
        && let Ok(document) = text.parse::<DocumentMut>()
        && dependency_tables_have_any_entries(&document)
    {
        let group_list = group_names.join(", ");
        return anyhow!(
            "No dependencies matched groups: [{group_list}] in {}",
            path.display()
        );
    }
    anyhow!("No belgie package dependencies found in {}", path.display())
}

fn install_result_from_env(env: &PackageEnvironment) -> PackageInstallResult {
    let mut groups = BTreeMap::new();
    for dep in env.dependencies() {
        match groups.get_mut(dep.group.as_str()) {
            Some(count) => *count += 1,
            None => {
                groups.insert(dep.group.clone(), 1);
            }
        }
    }
    PackageInstallResult {
        lockfile: env.lockfile().to_path_buf(),
        groups,
    }
}

fn read_manifest(
    cwd: &Path,
    groups: Option<Vec<String>>,
) -> Result<Option<PyprojectManifest>, AnyError> {
    let path = cwd.join("pyproject.toml");
    if !path.exists() {
        return Ok(None);
    }
    let text =
        std::fs::read_to_string(&path).with_context(|| format!("Reading {}", path.display()))?;
    let document = text
        .parse::<DocumentMut>()
        .with_context(|| format!("Parsing {}", path.display()))?;
    if document
        .get("belgie")
        .and_then(|belgie| belgie.get("dev-dependencies"))
        .is_some()
    {
        bail!("Unsupported table [belgie.dev-dependencies]; use [belgie.dependencies.dev] instead");
    }
    let group_filter = groups.map(|names| names.into_iter().collect::<BTreeSet<_>>());
    let mut dependencies = Vec::new();
    collect_dependency_groups(&document, group_filter.as_ref(), &mut dependencies)?;
    let mut scripts = BTreeMap::new();
    collect_scripts(&document, &mut scripts)?;
    Ok(Some(PyprojectManifest {
        path,
        document,
        dependencies,
        scripts,
    }))
}

pub(crate) fn dependencies_from_folder(
    cwd: &Path,
    groups: Option<Vec<String>>,
) -> Result<Vec<PackageDependency>, AnyError> {
    let Some(manifest) = read_manifest(cwd, groups.clone())? else {
        if groups.is_some() {
            return Err(no_dependencies_error(cwd, groups));
        }
        return Ok(Vec::new());
    };
    if manifest.dependencies.is_empty() && groups.is_some() {
        return Err(no_dependencies_error(cwd, groups));
    }
    Ok(manifest.dependencies)
}

pub(crate) fn dependencies_from_mapping(
    dependencies: BTreeMap<String, String>,
) -> Result<Vec<PackageDependency>, AnyError> {
    dependencies
        .into_iter()
        .map(|(alias, specifier)| normalize_dependency(&alias, &specifier, DEFAULT_GROUP))
        .collect()
}

pub(crate) fn find_pyproject_dir(start: &Path) -> Result<PathBuf, AnyError> {
    let start = start.canonicalize().unwrap_or_else(|_| start.to_path_buf());
    let mut searched = Vec::new();
    for dir in start.ancestors() {
        let path = dir.join("pyproject.toml");
        searched.push(path.display().to_string());
        if !path.is_file() {
            continue;
        }
        let text = std::fs::read_to_string(&path)
            .with_context(|| format!("Reading {}", path.display()))?;
        let document = text
            .parse::<DocumentMut>()
            .with_context(|| format!("Parsing {}", path.display()))?;
        if document.get("belgie").is_some() {
            return Ok(dir.to_path_buf());
        }
    }
    bail!(
        "Could not find pyproject.toml with a [belgie] table. Searched: {}",
        searched.join(", ")
    )
}

fn resolve_task_manifest(
    task_cwd: &Path,
    script_name: &str,
) -> Result<(PathBuf, Vec<PackageDependency>, String), AnyError> {
    let pyproject_dir = find_pyproject_dir(task_cwd)?;
    let manifest = read_manifest(&pyproject_dir, None)?.ok_or_else(|| {
        anyhow!(
            "No pyproject.toml with [belgie] configuration found near {}",
            task_cwd.display()
        )
    })?;
    let command = manifest.scripts.get(script_name).ok_or_else(|| {
        anyhow!(
            "No [belgie.scripts] entry '{script_name}' in {}",
            manifest.path.display()
        )
    })?;
    if manifest.dependencies.is_empty() {
        bail!(
            "No belgie package dependencies found in {}",
            manifest.path.display()
        );
    }
    Ok((pyproject_dir, manifest.dependencies, command.to_owned()))
}

fn collect_scripts(
    document: &DocumentMut,
    scripts: &mut BTreeMap<String, String>,
) -> Result<(), AnyError> {
    let Some(table) = document
        .get("belgie")
        .and_then(|belgie| belgie.get("scripts"))
        .and_then(|scripts| scripts.as_table())
    else {
        return Ok(());
    };

    for (name, item) in table.iter() {
        let command = item.as_str().ok_or_else(|| {
            anyhow!("[belgie.scripts] entry '{name}' must be a string shell command")
        })?;
        scripts.insert(name.to_string(), command.to_string());
    }
    Ok(())
}

fn group_is_included(group: &str, groups: Option<&BTreeSet<String>>) -> bool {
    match groups {
        None => true,
        Some(names) => names.contains(group),
    }
}

fn push_unique_dep(
    dep: PackageDependency,
    seen_aliases: &mut BTreeSet<String>,
    dependencies: &mut Vec<PackageDependency>,
) -> Result<(), AnyError> {
    if !seen_aliases.insert(dep.alias.clone()) {
        bail!(
            "Duplicate dependency alias '{}' across included groups",
            dep.alias
        );
    }
    dependencies.push(dep);
    Ok(())
}

fn collect_dependency_groups(
    document: &DocumentMut,
    groups: Option<&BTreeSet<String>>,
    dependencies: &mut Vec<PackageDependency>,
) -> Result<(), AnyError> {
    let Some(table) = document
        .get("belgie")
        .and_then(|belgie| belgie.get("dependencies"))
        .and_then(|deps| deps.as_table())
    else {
        return Ok(());
    };

    let include_default = group_is_included(DEFAULT_GROUP, groups);
    let mut seen_aliases = BTreeSet::new();
    for (key, item) in table.iter() {
        if let Some(raw_value) = item.as_str() {
            if !include_default {
                continue;
            }
            push_unique_dep(
                normalize_dependency(key, raw_value, DEFAULT_GROUP)?,
                &mut seen_aliases,
                dependencies,
            )?;
        } else if let Some(subtable) = item.as_table() {
            if !group_is_included(key, groups) {
                continue;
            }
            for (alias, subitem) in subtable.iter() {
                let raw_value = subitem.as_str().ok_or_else(|| {
                    anyhow!(
                        "[belgie.dependencies.{key}] entry '{alias}' must be a string dependency specifier"
                    )
                })?;
                push_unique_dep(
                    normalize_dependency(alias, raw_value, key)?,
                    &mut seen_aliases,
                    dependencies,
                )?;
            }
        } else {
            bail!(
                "[belgie.dependencies] entry '{key}' must be a string dependency specifier or nested dependency group table"
            );
        }
    }
    Ok(())
}

fn normalize_dependency(
    alias: &str,
    raw_value: &str,
    group: &str,
) -> Result<PackageDependency, AnyError> {
    let (specifier, value_kind) = if raw_value.starts_with("npm:") || raw_value.starts_with("jsr:")
    {
        (raw_value.to_string(), PyprojectValueKind::FullSpecifier)
    } else {
        (
            format!("npm:{alias}@{raw_value}"),
            PyprojectValueKind::VersionOnly,
        )
    };
    if !specifier.starts_with("npm:") && !specifier.starts_with("jsr:") {
        bail!("Belgie dependency '{alias}' must use an npm: or jsr: specifier, got '{raw_value}'");
    }
    Ok(PackageDependency {
        alias: alias.to_string(),
        specifier,
        group: group.to_string(),
        value_kind,
    })
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
      "nodeModulesDir": "none",
    });
    let text = serde_json::to_string_pretty(&config)?;
    std::fs::write(path, format!("{text}\n"))
        .with_context(|| format!("Writing {}", path.display()))?;
    Ok(())
}

pub(crate) fn read_synthetic_config_imports(
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
        .ok_or_else(|| anyhow!("Synthetic belgie Deno config is missing an imports table"))
}

fn apply_updates_to_pyproject(
    cwd: &Path,
    env: &PackageEnvironment,
) -> Result<Vec<PackageUpdateChange>, AnyError> {
    let mut manifest = read_manifest(cwd, None)?
        .ok_or_else(|| anyhow!("Missing {}", cwd.join("pyproject.toml").display()))?;
    let imports = read_synthetic_config_imports(env.config_file())?;

    let mut changes = Vec::new();
    for dep in env.dependencies() {
        let Some(updated_specifier) = imports.get(&dep.alias).and_then(|value| value.as_str())
        else {
            continue;
        };
        if updated_specifier == dep.specifier {
            continue;
        }
        let updated_value = dep.pyproject_value_for(updated_specifier)?;
        let previous =
            read_pyproject_dependency_value(&manifest.document, dep)?.unwrap_or_default();
        write_pyproject_dependency_value(&mut manifest.document, dep, &updated_value)?;
        changes.push(PackageUpdateChange {
            name: dep.alias.clone(),
            previous,
            updated: updated_value,
        });
    }

    if !changes.is_empty() {
        std::fs::write(&manifest.path, manifest.document.to_string())
            .with_context(|| format!("Writing {}", manifest.path.display()))?;
    }
    Ok(changes)
}

fn read_pyproject_dependency_value(
    document: &DocumentMut,
    dep: &PackageDependency,
) -> Result<Option<String>, AnyError> {
    let value = if dep.group == DEFAULT_GROUP {
        document["belgie"]["dependencies"][&dep.alias].clone()
    } else {
        document["belgie"]["dependencies"][&dep.group][&dep.alias].clone()
    };
    Ok(value.as_str().map(str::to_string))
}

fn write_pyproject_dependency_value(
    document: &mut DocumentMut,
    dep: &PackageDependency,
    updated_value: &str,
) -> Result<(), AnyError> {
    if dep.group == DEFAULT_GROUP {
        document["belgie"]["dependencies"][&dep.alias] = value(updated_value);
    } else {
        document["belgie"]["dependencies"][&dep.group][&dep.alias] = value(updated_value);
    }
    Ok(())
}

impl PackageDependency {
    fn is_npm(&self) -> bool {
        self.specifier.starts_with("npm:")
    }

    fn pyproject_value_for(&self, specifier: &str) -> Result<String, AnyError> {
        match self.value_kind {
            PyprojectValueKind::FullSpecifier => Ok(specifier.to_string()),
            PyprojectValueKind::VersionOnly => specifier
                .rsplit_once('@')
                .map(|(_, version_req)| version_req.to_string())
                .ok_or_else(|| {
                    anyhow!("Updated specifier '{specifier}' has no version requirement")
                }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn parse_manifest(text: &str, groups: Option<Vec<String>>) -> PyprojectManifest {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(temp_dir.path().join("pyproject.toml"), text).unwrap();
        read_manifest(temp_dir.path(), groups)
            .unwrap()
            .expect("manifest should exist")
    }

    fn parse_manifest_err(text: &str, groups: Option<Vec<String>>) -> AnyError {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(temp_dir.path().join("pyproject.toml"), text).unwrap();
        read_manifest(temp_dir.path(), groups).unwrap_err()
    }

    #[test]
    fn normalizes_unprefixed_dependencies_to_npm_imports() {
        let dep = normalize_dependency("react", "^19", DEFAULT_GROUP).unwrap();

        assert_eq!(dep.alias, "react");
        assert_eq!(dep.specifier, "npm:react@^19");
    }

    #[test]
    fn preserves_explicit_jsr_specifiers() {
        let dep = normalize_dependency("@std/path", "jsr:@std/path@^1", DEFAULT_GROUP).unwrap();

        assert_eq!(dep.specifier, "jsr:@std/path@^1");
    }

    #[test]
    fn extracts_updated_version_for_version_only_entries() {
        let dep = normalize_dependency("@types/react", "^19", "dev").unwrap();

        assert_eq!(
            dep.pyproject_value_for("npm:@types/react@^20").unwrap(),
            "^20"
        );
    }

    #[test]
    fn reads_pyproject_nested_dependency_groups() {
        let manifest = parse_manifest(
            r#"[project]
name = "example"

[belgie.dependencies]
react = "^19"
std_path = "jsr:@std/path@^1"

[belgie.dependencies.dev]
"@types/react" = "^19"

[belgie.dependencies.test]
vitest = "^1"
"#,
            None,
        );

        assert_eq!(manifest.dependencies.len(), 4);
        assert_eq!(manifest.dependencies[0].alias, "react");
        assert_eq!(manifest.dependencies[0].group, DEFAULT_GROUP);
        assert_eq!(manifest.dependencies[0].specifier, "npm:react@^19");
        assert_eq!(manifest.dependencies[1].specifier, "jsr:@std/path@^1");
        assert_eq!(manifest.dependencies[2].alias, "@types/react");
        assert_eq!(manifest.dependencies[2].group, "dev");
        assert_eq!(manifest.dependencies[3].alias, "vitest");
        assert_eq!(manifest.dependencies[3].group, "test");
    }

    #[test]
    fn groups_filter_limits_collected_dependencies() {
        let text = r#"[belgie.dependencies]
react = "^19"

[belgie.dependencies.dev]
"@types/react" = "^19"
"#;

        let default_only = parse_manifest(text, Some(vec!["default".to_string()]));
        assert_eq!(default_only.dependencies.len(), 1);
        assert_eq!(default_only.dependencies[0].alias, "react");

        let dev_only = parse_manifest(text, Some(vec!["dev".to_string()]));
        assert_eq!(dev_only.dependencies.len(), 1);
        assert_eq!(dev_only.dependencies[0].alias, "@types/react");

        let both = parse_manifest(text, Some(vec!["default".to_string(), "dev".to_string()]));
        assert_eq!(both.dependencies.len(), 2);
    }

    #[test]
    fn rejects_duplicate_aliases_across_groups() {
        let err = parse_manifest_err(
            r#"[belgie.dependencies]
react = "^19"

[belgie.dependencies.dev]
react = "^20"
"#,
            None,
        );
        assert!(
            err.to_string()
                .contains("Duplicate dependency alias 'react'")
        );
    }

    #[test]
    fn rejects_legacy_dev_dependencies_table() {
        let err = parse_manifest_err(
            r#"[belgie.dev-dependencies]
"@types/react" = "^19"
"#,
            None,
        );
        assert!(
            err.to_string()
                .contains("Unsupported table [belgie.dev-dependencies]")
        );
    }

    #[test]
    fn rejects_non_string_entries_in_nested_groups() {
        let err = parse_manifest_err(
            r#"[belgie.dependencies.dev]
react = ["^19"]
"#,
            None,
        );
        assert!(
            err.to_string()
                .contains("[belgie.dependencies.dev] entry 'react'")
        );
    }

    #[test]
    fn synthetic_config_contains_imports_and_disables_node_modules_dir() {
        let temp_dir = tempfile::tempdir().unwrap();
        let config_path = temp_dir.path().join("deno.json");
        let dependencies = vec![normalize_dependency("react", "^19", DEFAULT_GROUP).unwrap()];

        write_synthetic_config(&config_path, &dependencies).unwrap();

        let text = fs::read_to_string(config_path).unwrap();
        let config: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(config["imports"]["react"], "npm:react@^19");
        assert_eq!(config["nodeModulesDir"], "none");
    }

    #[test]
    fn applies_updates_back_to_default_group() {
        let temp_dir = tempfile::tempdir().unwrap();
        let cwd = temp_dir.path().to_path_buf();
        fs::write(
            cwd.join("pyproject.toml"),
            r#"[belgie.dependencies]
react = "^18"
std_path = "jsr:@std/path@^1"
"#,
        )
        .unwrap();
        let dependencies = vec![
            normalize_dependency("react", "^18", DEFAULT_GROUP).unwrap(),
            normalize_dependency("std_path", "jsr:@std/path@^1", DEFAULT_GROUP).unwrap(),
        ];
        let env = PackageEnvironment::from_dependencies(cwd.clone(), dependencies).unwrap();
        let mut config: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(env.config_file()).unwrap()).unwrap();
        config["imports"]["react"] = serde_json::Value::String("npm:react@^19".into());
        config["imports"]["std_path"] = serde_json::Value::String("jsr:@std/path@^2".into());
        fs::write(
            env.config_file(),
            serde_json::to_string_pretty(&config).unwrap(),
        )
        .unwrap();

        let changes = apply_updates_to_pyproject(&cwd, &env).unwrap();

        assert_eq!(changes.len(), 2);
        assert_eq!(changes[0].previous, "^18");
        assert_eq!(changes[0].updated, "^19");
        assert_eq!(changes[1].previous, "jsr:@std/path@^1");
        assert_eq!(changes[1].updated, "jsr:@std/path@^2");
        let pyproject = fs::read_to_string(cwd.join("pyproject.toml")).unwrap();
        assert!(pyproject.contains("react = \"^19\""));
        assert!(pyproject.contains("std_path = \"jsr:@std/path@^2\""));
    }

    #[test]
    fn applies_updates_back_to_named_group() {
        let temp_dir = tempfile::tempdir().unwrap();
        let cwd = temp_dir.path().to_path_buf();
        fs::write(
            cwd.join("pyproject.toml"),
            r#"[belgie.dependencies.dev]
"@types/react" = "^18"
"#,
        )
        .unwrap();
        let dependencies = vec![normalize_dependency("@types/react", "^18", "dev").unwrap()];
        let env = PackageEnvironment::from_dependencies(cwd.clone(), dependencies).unwrap();
        let mut config: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(env.config_file()).unwrap()).unwrap();
        config["imports"]["@types/react"] =
            serde_json::Value::String("npm:@types/react@^19".into());
        fs::write(
            env.config_file(),
            serde_json::to_string_pretty(&config).unwrap(),
        )
        .unwrap();

        let changes = apply_updates_to_pyproject(&cwd, &env).unwrap();

        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].updated, "^19");
        let pyproject = fs::read_to_string(cwd.join("pyproject.toml")).unwrap();
        assert!(pyproject.contains("\"@types/react\" = \"^19\""));
    }

    #[test]
    fn reads_pyproject_script_table() {
        let manifest = parse_manifest(
            r#"[project]
name = "example"

[belgie.dependencies]
vite = "^8"

[belgie.scripts]
build = "vite build"
dev = "vite"
"#,
            None,
        );

        assert_eq!(
            manifest.scripts.get("build"),
            Some(&"vite build".to_string())
        );
        assert_eq!(manifest.scripts.get("dev"), Some(&"vite".to_string()));
    }

    #[test]
    fn resolve_task_returns_command_string() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            r#"[belgie.dependencies]
vite = "^8"

[belgie.scripts]
build = "vite build"
"#,
        )
        .unwrap();
        fs::write(temp_dir.path().join("deno.lock"), EMPTY_DENO_LOCK).unwrap();
        fs::create_dir(temp_dir.path().join("node_modules")).unwrap();

        let (env, command) =
            PackageEnvironment::resolve_task(temp_dir.path(), "build", false).unwrap();

        assert_eq!(command, "vite build");
        assert!(
            env.config_file()
                .to_string_lossy()
                .contains("belgie-packages-")
        );
        assert!(!temp_dir.path().join(".belgie").exists());
        let config: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(env.config_file()).unwrap()).unwrap();
        assert!(config.get("tasks").is_none());
        let node_modules = temp_dir.path().join("node_modules").canonicalize().unwrap();
        assert_eq!(
            env.embed_context()
                .unwrap()
                .resolver_factory()
                .workspace_factory()
                .node_modules_dir_path()
                .unwrap(),
            Some(node_modules.as_path())
        );
    }

    #[test]
    fn project_environment_requires_lockfile() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            "[belgie.dependencies]\nreact = \"^19\"\n",
        )
        .unwrap();

        let error =
            ProjectPackageEnvironment::from_folder(temp_dir.path().to_path_buf(), None, false)
                .unwrap_err();

        assert!(error.to_string().contains("missing"));
        assert!(error.to_string().contains("deno.lock"));
    }

    #[test]
    fn project_environment_requires_node_modules_for_npm_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            "[belgie.dependencies]\nreact = \"^19\"\n",
        )
        .unwrap();
        fs::write(temp_dir.path().join("deno.lock"), EMPTY_DENO_LOCK).unwrap();

        let error =
            ProjectPackageEnvironment::from_folder(temp_dir.path().to_path_buf(), None, false)
                .unwrap_err();

        assert!(error.to_string().contains("node_modules"));
        assert!(error.to_string().contains("install=True"));
    }

    #[test]
    fn project_environment_allows_jsr_dependencies_without_node_modules() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            "[belgie.dependencies]\nstd_path = \"jsr:@std/path@^1\"\n",
        )
        .unwrap();
        fs::write(temp_dir.path().join("deno.lock"), EMPTY_DENO_LOCK).unwrap();

        let environment =
            ProjectPackageEnvironment::from_folder(temp_dir.path().to_path_buf(), None, false)
                .unwrap();

        assert!(environment.is_some());
        assert!(!temp_dir.path().join("node_modules").exists());
        assert!(!temp_dir.path().join("deno.json").exists());
    }

    #[test]
    fn find_pyproject_dir_walks_ancestors() {
        let temp_dir = tempfile::tempdir().unwrap();
        let nested = temp_dir.path().join("src").join("app").join("views");
        fs::create_dir_all(&nested).unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            "[belgie.dependencies]\nvite = \"^8\"\n",
        )
        .unwrap();

        let found = find_pyproject_dir(&nested).unwrap();

        assert_eq!(found, temp_dir.path().canonicalize().unwrap());
    }

    #[test]
    fn required_reports_unmatched_groups_when_filter_excludes_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            r#"[belgie.dependencies]
react = "^19"

[belgie.dependencies.dev]
"@types/react" = "^19"
"#,
        )
        .unwrap();

        let err = PackageEnvironment::required(
            temp_dir.path().to_path_buf(),
            Some(vec!["typo".to_string()]),
            EmbedContextOptions::default(),
        )
        .unwrap_err();

        assert!(
            err.to_string()
                .contains("No dependencies matched groups: [typo]")
        );
    }

    #[test]
    fn from_folder_reports_unmatched_groups_when_filter_excludes_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            "[belgie.dependencies]\nreact = \"^19\"\n",
        )
        .unwrap();

        let err = ProjectPackageEnvironment::from_folder(
            temp_dir.path().to_path_buf(),
            Some(vec!["typo".to_string()]),
            false,
        )
        .unwrap_err();

        assert!(
            err.to_string()
                .contains("No dependencies matched groups: [typo]")
        );
    }

    #[test]
    fn from_folder_reports_missing_dependencies_when_groups_are_explicit() {
        let temp_dir = tempfile::tempdir().unwrap();

        let err = ProjectPackageEnvironment::from_folder(
            temp_dir.path().to_path_buf(),
            Some(vec!["default".to_string()]),
            false,
        )
        .unwrap_err();

        assert!(
            err.to_string()
                .contains("No belgie package dependencies found")
        );
    }

    #[test]
    fn from_folder_allows_missing_manifest_without_explicit_groups() {
        let temp_dir = tempfile::tempdir().unwrap();

        let environment =
            ProjectPackageEnvironment::from_folder(temp_dir.path().to_path_buf(), None, false)
                .unwrap();

        assert!(environment.is_none());
    }

    #[test]
    fn resolve_task_loads_dependencies_from_all_groups() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            r#"[belgie.dependencies.dev]
vite = "^8"

[belgie.scripts]
build = "vite build"
"#,
        )
        .unwrap();
        fs::write(temp_dir.path().join("deno.lock"), EMPTY_DENO_LOCK).unwrap();
        fs::create_dir(temp_dir.path().join("node_modules")).unwrap();

        let (env, command) =
            PackageEnvironment::resolve_task(temp_dir.path(), "build", false).unwrap();

        assert_eq!(command, "vite build");
        assert_eq!(env.dependencies().len(), 1);
        assert_eq!(env.dependencies()[0].alias, "vite");
        assert_eq!(env.dependencies()[0].group, "dev");
    }

    #[test]
    fn resolve_task_rejects_projects_without_dependencies() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            r#"[belgie.scripts]
build = "echo ok"
"#,
        )
        .unwrap();

        let err = PackageEnvironment::resolve_task(temp_dir.path(), "build", false).unwrap_err();

        assert!(
            err.to_string()
                .contains("No belgie package dependencies found")
        );
    }
}
