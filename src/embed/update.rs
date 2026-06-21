use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

use deno_core::anyhow::{Context, anyhow, bail};
use deno_core::error::AnyError;
use deno_core::serde_json;
use deno_core::url::Url;
use deno_graph::packages::JsrPackageInfo;
use deno_npm::registry::NpmPackageInfo;
use deno_npm::resolution::NpmPackageVersionResolver;
use deno_semver::jsr::JsrPackageReqReference;
use deno_semver::npm::NpmPackageReqReference;
use deno_semver::package::PackageReq;
use deno_semver::{Version, VersionReq};

use crate::embed::context::{EmbedContext, EmbedContextOptions};
use crate::embed::install::install_packages_with_options;

struct FilterEntry {
    alias: String,
    version_req: Option<String>,
}

pub(crate) async fn update_packages(
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    filters: Vec<String>,
    latest: bool,
    lockfile_only: bool,
    options: EmbedContextOptions,
) -> Result<(), AnyError> {
    let context_options = options.clone().for_package_manager();
    let context = EmbedContext::new_with_options(
        cwd.clone(),
        config_file.clone(),
        lockfile.clone(),
        context_options,
    )?;
    let filter_entries = parse_filters(&filters);
    let text = std::fs::read_to_string(&config_file)
        .with_context(|| format!("Reading {}", config_file.display()))?;
    let mut config: serde_json::Value = serde_json::from_str(&text)
        .with_context(|| format!("Parsing {}", config_file.display()))?;
    let imports_snapshot = config
        .get("imports")
        .and_then(|value| value.as_object())
        .ok_or_else(|| anyhow!("Synthetic belgie Deno config is missing an imports table"))?;
    let aliases_to_update = resolve_aliases_to_update(imports_snapshot, &filter_entries)?;
    if aliases_to_update.is_empty() {
        return Ok(());
    }

    let imports = config
        .get_mut("imports")
        .and_then(|value| value.as_object_mut())
        .ok_or_else(|| anyhow!("Synthetic belgie Deno config is missing an imports table"))?;

    let explicit_versions = filter_entries
        .iter()
        .filter_map(|entry| {
            entry
                .version_req
                .as_ref()
                .map(|version| (entry.alias.clone(), version.clone()))
        })
        .collect::<HashMap<_, _>>();

    for alias in aliases_to_update {
        let Some(current) = imports.get(&alias).and_then(|value| value.as_str()) else {
            continue;
        };
        let explicit = explicit_versions.get(&alias).map(String::as_str);
        let updated = resolve_updated_specifier(&context, current, latest, explicit).await?;
        imports.insert(alias, serde_json::Value::String(updated));
    }

    std::fs::write(
        &config_file,
        format!("{}\n", serde_json::to_string_pretty(&config)?),
    )
    .with_context(|| format!("Writing {}", config_file.display()))?;

    install_packages_with_options(cwd, config_file, lockfile, lockfile_only, options)
        .await
        .map(|_| ())
}

fn parse_filters(filters: &[String]) -> Vec<FilterEntry> {
    filters
        .iter()
        .map(|filter| {
            if let Some((alias, version_req)) = filter.rsplit_once('@')
                && !alias.is_empty()
            {
                FilterEntry {
                    alias: alias.to_string(),
                    version_req: Some(format!("@{version_req}")),
                }
            } else {
                FilterEntry {
                    alias: filter.clone(),
                    version_req: None,
                }
            }
        })
        .collect()
}

fn resolve_aliases_to_update(
    imports: &serde_json::Map<String, serde_json::Value>,
    filters: &[FilterEntry],
) -> Result<Vec<String>, AnyError> {
    if filters.is_empty() {
        return Ok(imports.keys().cloned().collect());
    }

    let filter_aliases = filters
        .iter()
        .map(|entry| entry.alias.as_str())
        .collect::<HashSet<_>>();
    Ok(imports
        .keys()
        .filter(|alias| filter_aliases.contains(alias.as_str()))
        .cloned()
        .collect())
}

async fn resolve_updated_specifier(
    context: &EmbedContext,
    current: &str,
    latest: bool,
    explicit_version: Option<&str>,
) -> Result<String, AnyError> {
    if let Some(version_req) = explicit_version {
        return replace_specifier_version(current, version_req);
    }
    if current.starts_with("npm:") {
        resolve_npm_specifier(context, current, latest).await
    } else if current.starts_with("jsr:") {
        resolve_jsr_specifier(context, current, latest).await
    } else {
        bail!("Unsupported dependency specifier '{current}'")
    }
}

fn replace_specifier_version(current: &str, version_req: &str) -> Result<String, AnyError> {
    let version_req = version_req.strip_prefix('@').unwrap_or(version_req);
    if version_req.starts_with("npm:") || version_req.starts_with("jsr:") {
        return Ok(version_req.to_string());
    }
    if let Ok(req_ref) = NpmPackageReqReference::from_str(current) {
        return Ok(format!("npm:{}@{version_req}", req_ref.req().name));
    }
    if let Ok(req_ref) = JsrPackageReqReference::from_str(current) {
        return Ok(format!("jsr:{}@{version_req}", req_ref.req().name));
    }
    bail!("Unsupported dependency specifier '{current}'")
}

async fn resolve_npm_specifier(
    context: &EmbedContext,
    current: &str,
    latest: bool,
) -> Result<String, AnyError> {
    let req_ref = NpmPackageReqReference::from_str(current)
        .with_context(|| format!("Parsing npm dependency specifier '{current}'"))?;
    let req = req_ref.req().clone();
    let registry = context.npm_installer_factory().registry_info_provider()?;
    let npm_version_resolver = context.resolver_factory().npm_version_resolver()?;
    let Some(info) = registry.maybe_package_info(&req.name).await? else {
        bail!("npm package '{}' was not found", req.name);
    };
    let version_resolver = npm_version_resolver.get_for_package(&info);
    let compatible = version_resolver
        .resolve_best_package_version_info(&req.version_req, Vec::new().into_iter())?
        .version
        .clone();
    let target_version = if latest {
        resolve_npm_latest_version(&info, &req, &version_resolver)?
    } else {
        resolve_npm_compatible_version(&info, &req, &compatible, &version_resolver)?
    };
    let operator = preserve_version_operator(&req.version_req);
    let new_req = VersionReq::parse_from_specifier(&format!("{operator}{target_version}"))?;
    Ok(format!("npm:{}@{new_req}", req.name))
}

fn resolve_npm_latest_version(
    info: &NpmPackageInfo,
    req: &PackageReq,
    version_resolver: &NpmPackageVersionResolver<'_>,
) -> Result<Version, AnyError> {
    let latest_tag = info
        .dist_tags
        .get("latest")
        .ok_or_else(|| anyhow!("npm package '{}' is missing a latest dist-tag", req.name))?;
    if version_resolver.matches_newest_dependency_date(latest_tag) {
        Ok(latest_tag.clone())
    } else {
        bail!(
            "npm package '{}' latest version '{}' is excluded by dependency age policy",
            req.name,
            latest_tag
        )
    }
}

fn resolve_npm_compatible_version(
    info: &NpmPackageInfo,
    req: &PackageReq,
    compatible: &Version,
    version_resolver: &NpmPackageVersionResolver<'_>,
) -> Result<Version, AnyError> {
    if let Some(latest_tag) = info.dist_tags.get("latest")
        && version_resolver
            .version_req_satisfies_and_matches_newest_dependency_date(&req.version_req, latest_tag)
            .unwrap_or(false)
        && latest_tag > compatible
    {
        return Ok(latest_tag.clone());
    }
    Ok(compatible.clone())
}

async fn resolve_jsr_specifier(
    context: &EmbedContext,
    current: &str,
    latest: bool,
) -> Result<String, AnyError> {
    let req_ref = JsrPackageReqReference::from_str(current)
        .with_context(|| format!("Parsing jsr dependency specifier '{current}'"))?;
    let req = req_ref.req().clone();
    let package_info = fetch_jsr_package_info(context, &req.name).await?;
    let jsr_version_resolver = context.resolver_factory().jsr_version_resolver()?;
    let version_resolver = jsr_version_resolver.get_for_package(&req.name, &package_info);
    let compatible = version_resolver
        .resolve_version(&req, Vec::new().into_iter())?
        .version
        .clone();
    let target_version = if latest {
        resolve_jsr_latest_version(&package_info, &compatible, &version_resolver)?
    } else {
        resolve_jsr_compatible_version(&package_info, &compatible, &version_resolver)?
    };
    let operator = preserve_version_operator(&req.version_req);
    let new_req = VersionReq::parse_from_specifier(&format!("{operator}{target_version}"))?;
    Ok(format!("jsr:{}@{new_req}", req.name))
}

async fn fetch_jsr_package_info(
    context: &EmbedContext,
    name: &str,
) -> Result<JsrPackageInfo, AnyError> {
    let meta_url = Url::parse(&format!("https://jsr.io/{name}/meta.json"))
        .with_context(|| format!("Building JSR metadata URL for '{name}'"))?;
    let body = context
        .http_client()
        .fetch_bytes(&meta_url)
        .await
        .map_err(|err| anyhow!(err.to_string()))?;
    serde_json::from_slice(&body).with_context(|| format!("Parsing JSR metadata for '{name}'"))
}

fn resolve_jsr_latest_version(
    package_info: &JsrPackageInfo,
    lower_bound: &Version,
    version_resolver: &deno_graph::packages::JsrPackageVersionResolver<'_>,
) -> Result<Version, AnyError> {
    let mut best = Some(lower_bound.clone());
    for (version, version_info) in &package_info.versions {
        if version_info.yanked || !version_resolver.matches_newest_dependency_date(version_info) {
            continue;
        }
        if best.as_ref().is_none_or(|current| version > current) {
            best = Some(version.clone());
        }
    }
    best.ok_or_else(|| anyhow!("No JSR versions matched the dependency policy"))
}

fn resolve_jsr_compatible_version(
    package_info: &JsrPackageInfo,
    compatible: &Version,
    version_resolver: &deno_graph::packages::JsrPackageVersionResolver<'_>,
) -> Result<Version, AnyError> {
    let mut best = Some(compatible.clone());
    for (version, version_info) in &package_info.versions {
        if version_info.yanked
            || !version_resolver.matches_newest_dependency_date(version_info)
            || version <= compatible
        {
            continue;
        }
        if best.as_ref().is_none_or(|current| version > current) {
            best = Some(version.clone());
        }
    }
    best.ok_or_else(|| anyhow!("No newer compatible JSR version was found"))
}

fn preserve_version_operator(version_req: &VersionReq) -> &'static str {
    let version_req_str = version_req.to_string();
    if version_req_str.starts_with('~') {
        "~"
    } else if version_req_str.starts_with('^') {
        "^"
    } else if version_req
        .range()
        .is_some_and(|range| range.0[0].start == range.0[0].end)
    {
        ""
    } else {
        "^"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_filters_with_explicit_versions() {
        let filters = parse_filters(&[
            "react".to_string(),
            "std_path@^2".to_string(),
            "@types/react".to_string(),
            "@types/react@^20".to_string(),
        ]);

        assert_eq!(filters[0].alias, "react");
        assert!(filters[0].version_req.is_none());
        assert_eq!(filters[1].alias, "std_path");
        assert_eq!(filters[1].version_req.as_deref(), Some("@^2"));
        assert_eq!(filters[2].alias, "@types/react");
        assert!(filters[2].version_req.is_none());
        assert_eq!(filters[3].alias, "@types/react");
        assert_eq!(filters[3].version_req.as_deref(), Some("@^20"));
    }

    #[test]
    fn resolves_scoped_alias_filters() {
        let imports = serde_json::Map::from_iter([
            (
                "react".to_string(),
                serde_json::Value::String("npm:react@^19".to_string()),
            ),
            (
                "@types/react".to_string(),
                serde_json::Value::String("npm:@types/react@^19".to_string()),
            ),
        ]);
        let filters = parse_filters(&["@types/react@^20".to_string()]);

        let aliases = resolve_aliases_to_update(&imports, &filters).unwrap();

        assert_eq!(aliases, vec!["@types/react"]);
    }

    #[test]
    fn replaces_npm_specifier_versions() {
        let updated = replace_specifier_version("npm:react@^18", "^19").unwrap();

        assert_eq!(updated, "npm:react@^19");
    }

    #[test]
    fn replaces_jsr_specifier_versions() {
        let updated = replace_specifier_version("jsr:@std/path@^1", "^2").unwrap();

        assert_eq!(updated, "jsr:@std/path@^2");
    }
}
