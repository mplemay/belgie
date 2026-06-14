use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::Mutex;

use deno_core::anyhow::{Context, anyhow, bail};
use deno_core::error::AnyError;
use deno_core::serde_json;
use tempfile::TempDir;
use toml_edit::{DocumentMut, value};

use crate::embed::EmbedContext;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum DependencyKind {
    Dependency,
    DevDependency,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum PyprojectValueKind {
    VersionOnly,
    FullSpecifier,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PackageDependency {
    alias: String,
    specifier: String,
    kind: DependencyKind,
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
    embed_context: Mutex<Option<Rc<EmbedContext>>>,
    _temp_dir: TempDir,
}

#[derive(Clone, Debug)]
pub(crate) struct PackageInstallResult {
    pub lockfile: PathBuf,
    pub dependencies: usize,
    pub dev_dependencies: usize,
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

struct PyprojectManifest {
    path: PathBuf,
    document: DocumentMut,
    dependencies: Vec<PackageDependency>,
    scripts: BTreeMap<String, String>,
}

impl PackageEnvironment {
    pub(crate) fn discover(cwd: PathBuf, include_dev: bool) -> Result<Option<Self>, AnyError> {
        let Some(manifest) = read_manifest(&cwd, include_dev)? else {
            return Ok(None);
        };
        if manifest.dependencies.is_empty() {
            return Ok(None);
        }
        Self::from_dependencies(cwd, manifest.dependencies).map(Some)
    }

    fn required(cwd: PathBuf, include_dev: bool) -> Result<Self, AnyError> {
        Self::discover(cwd.clone(), include_dev)?.ok_or_else(|| {
            anyhow!(
                "No belgie package dependencies found in {}",
                cwd.join("pyproject.toml").display()
            )
        })
    }

    fn from_dependencies(
        cwd: PathBuf,
        dependencies: Vec<PackageDependency>,
    ) -> Result<Self, AnyError> {
        Self::from_manifest_parts(cwd, dependencies)
    }

    fn from_manifest_parts(
        cwd: PathBuf,
        dependencies: Vec<PackageDependency>,
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
                embed_context: Mutex::new(None),
                _temp_dir: temp_dir,
            }),
        })
    }

    pub(crate) fn resolve_task(
        task_cwd: &Path,
        script_name: &str,
    ) -> Result<(Self, String), AnyError> {
        let pyproject_dir = find_pyproject_dir(task_cwd)?;
        let manifest = read_manifest(&pyproject_dir, true)?.ok_or_else(|| {
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
        let env = Self::from_manifest_parts(pyproject_dir, manifest.dependencies)?;
        Ok((env, command.to_owned()))
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
            *guard = Some(Rc::new(EmbedContext::new(cwd, config_file, lockfile)?));
        }
        Ok(guard
            .as_ref()
            .expect("embed context should be initialized")
            .clone())
    }
}

pub(crate) async fn install_packages(
    cwd: PathBuf,
    include_dev: bool,
    lockfile_only: bool,
) -> Result<PackageInstallResult, AnyError> {
    let env = PackageEnvironment::required(cwd, include_dev)?;
    let (cwd, config_file, lockfile) = env.embed_paths();
    crate::embed::install_packages(cwd, config_file, lockfile, lockfile_only).await?;
    Ok(install_result_from_env(&env))
}

pub(crate) async fn lock_packages(
    cwd: PathBuf,
    include_dev: bool,
) -> Result<PackageInstallResult, AnyError> {
    install_packages(cwd, include_dev, true).await
}

pub(crate) async fn update_packages(
    cwd: PathBuf,
    packages: Vec<String>,
    include_dev: bool,
    latest: bool,
    lockfile_only: bool,
) -> Result<PackageUpdateResult, AnyError> {
    let env = PackageEnvironment::required(cwd.clone(), include_dev)?;
    let (project_cwd, config_file, lockfile) = env.embed_paths();
    crate::embed::update_packages(
        project_cwd,
        config_file,
        lockfile,
        packages,
        latest,
        lockfile_only,
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

fn install_result_from_env(env: &PackageEnvironment) -> PackageInstallResult {
    let dependencies = env
        .dependencies()
        .iter()
        .filter(|dep| dep.kind == DependencyKind::Dependency)
        .count();
    let dev_dependencies = env
        .dependencies()
        .iter()
        .filter(|dep| dep.kind == DependencyKind::DevDependency)
        .count();
    PackageInstallResult {
        lockfile: env.lockfile().to_path_buf(),
        dependencies,
        dev_dependencies,
    }
}

fn read_manifest(cwd: &Path, include_dev: bool) -> Result<Option<PyprojectManifest>, AnyError> {
    let path = cwd.join("pyproject.toml");
    if !path.exists() {
        return Ok(None);
    }
    let text =
        std::fs::read_to_string(&path).with_context(|| format!("Reading {}", path.display()))?;
    let document = text
        .parse::<DocumentMut>()
        .with_context(|| format!("Parsing {}", path.display()))?;
    let mut dependencies = Vec::new();
    collect_table_deps(&document, DependencyKind::Dependency, &mut dependencies)?;
    if include_dev {
        collect_table_deps(&document, DependencyKind::DevDependency, &mut dependencies)?;
    }
    let mut scripts = BTreeMap::new();
    collect_scripts(&document, &mut scripts)?;
    Ok(Some(PyprojectManifest {
        path,
        document,
        dependencies,
        scripts,
    }))
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

fn collect_table_deps(
    document: &DocumentMut,
    kind: DependencyKind,
    dependencies: &mut Vec<PackageDependency>,
) -> Result<(), AnyError> {
    let table_name = match kind {
        DependencyKind::Dependency => "dependencies",
        DependencyKind::DevDependency => "dev-dependencies",
    };
    let Some(table) = document
        .get("belgie")
        .and_then(|deno| deno.get(table_name))
        .and_then(|deps| deps.as_table())
    else {
        return Ok(());
    };

    for (alias, item) in table.iter() {
        let raw_value = item.as_str().ok_or_else(|| {
            anyhow!("[belgie.{table_name}] entry '{alias}' must be a string dependency specifier")
        })?;
        dependencies.push(normalize_dependency(alias, raw_value, kind)?);
    }
    Ok(())
}

fn normalize_dependency(
    alias: &str,
    raw_value: &str,
    kind: DependencyKind,
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
        kind,
        value_kind,
    })
}

fn write_synthetic_config(path: &Path, dependencies: &[PackageDependency]) -> Result<(), AnyError> {
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
    let mut manifest = read_manifest(cwd, true)?
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
        let table_name = match dep.kind {
            DependencyKind::Dependency => "dependencies",
            DependencyKind::DevDependency => "dev-dependencies",
        };
        let previous = manifest.document["belgie"][table_name][&dep.alias]
            .as_str()
            .unwrap_or("")
            .to_string();
        manifest.document["belgie"][table_name][&dep.alias] = value(&updated_value);
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

impl PackageDependency {
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

    #[test]
    fn normalizes_unprefixed_dependencies_to_npm_imports() {
        let dep = normalize_dependency("react", "^19", DependencyKind::Dependency).unwrap();

        assert_eq!(dep.alias, "react");
        assert_eq!(dep.specifier, "npm:react@^19");
    }

    #[test]
    fn preserves_explicit_jsr_specifiers() {
        let dep = normalize_dependency("@std/path", "jsr:@std/path@^1", DependencyKind::Dependency)
            .unwrap();

        assert_eq!(dep.specifier, "jsr:@std/path@^1");
    }

    #[test]
    fn extracts_updated_version_for_version_only_entries() {
        let dep =
            normalize_dependency("@types/react", "^19", DependencyKind::DevDependency).unwrap();

        assert_eq!(
            dep.pyproject_value_for("npm:@types/react@^20").unwrap(),
            "^20"
        );
    }

    #[test]
    fn reads_pyproject_deno_dependency_tables() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            r#"[project]
name = "example"

[belgie.dependencies]
react = "^19"
std_path = "jsr:@std/path@^1"

[belgie.dev-dependencies]
"@types/react" = "^19"
"#,
        )
        .unwrap();

        let manifest = read_manifest(temp_dir.path(), true).unwrap().unwrap();
        let prod_manifest = read_manifest(temp_dir.path(), false).unwrap().unwrap();

        assert_eq!(manifest.dependencies.len(), 3);
        assert_eq!(prod_manifest.dependencies.len(), 2);
        assert_eq!(manifest.dependencies[0].alias, "react");
        assert_eq!(manifest.dependencies[0].specifier, "npm:react@^19");
        assert_eq!(manifest.dependencies[1].specifier, "jsr:@std/path@^1");
        assert_eq!(manifest.dependencies[2].alias, "@types/react");
        assert_eq!(manifest.dependencies[2].kind, DependencyKind::DevDependency);
    }

    #[test]
    fn synthetic_config_contains_imports_and_disables_node_modules_dir() {
        let temp_dir = tempfile::tempdir().unwrap();
        let config_path = temp_dir.path().join("deno.json");
        let dependencies =
            vec![normalize_dependency("react", "^19", DependencyKind::Dependency).unwrap()];

        write_synthetic_config(&config_path, &dependencies).unwrap();

        let text = fs::read_to_string(config_path).unwrap();
        let config: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(config["imports"]["react"], "npm:react@^19");
        assert_eq!(config["nodeModulesDir"], "none");
    }

    #[test]
    fn applies_updates_back_to_pyproject_values() {
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
            normalize_dependency("react", "^18", DependencyKind::Dependency).unwrap(),
            normalize_dependency("std_path", "jsr:@std/path@^1", DependencyKind::Dependency)
                .unwrap(),
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
    fn reads_pyproject_script_table() {
        let temp_dir = tempfile::tempdir().unwrap();
        fs::write(
            temp_dir.path().join("pyproject.toml"),
            r#"[project]
name = "example"

[belgie.dependencies]
vite = "^8"

[belgie.scripts]
build = "vite build"
dev = "vite"
"#,
        )
        .unwrap();

        let manifest = read_manifest(temp_dir.path(), true).unwrap().unwrap();

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

        let (env, command) = PackageEnvironment::resolve_task(temp_dir.path(), "build").unwrap();

        assert_eq!(command, "vite build");
        let config: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(env.config_file()).unwrap()).unwrap();
        assert!(config.get("tasks").is_none());
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
}
