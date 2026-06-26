use std::collections::{HashMap, HashSet};

use deno_core::error::AnyError;
use deno_graph::{
    CheckJsOption, GraphKind, ModuleErrorKind, ModuleGraph, ModuleGraphError, ModuleSpecifier,
    WalkOptions,
};
use deno_media_type::MediaType;
use deno_resolver::deno_json::JsxImportSourceConfigResolver;
use deno_resolver::factory::ResolverFactory;
use deno_resolver::graph::NpmTypesResolutionMode;
use deno_resolver::loader::AllowJsonImports;
use deno_semver::jsr::JsrPackageReqReference;

use crate::embed::context::EmbedContext;
use crate::embed::sys::EmbedSys;

// Trimmed from Deno's cli/tools/pm/cache_deps.rs import-map root loop.
async fn collect_import_map_roots(
    resolver_factory: &ResolverFactory<EmbedSys>,
) -> Result<Vec<ModuleSpecifier>, AnyError> {
    let workspace_resolver = resolver_factory.workspace_resolver().await?;
    let mut roots = Vec::new();
    let mut seen_reqs = HashSet::new();

    let Some(import_map) = workspace_resolver.maybe_import_map() else {
        return Ok(roots);
    };

    for entry in import_map.imports().entries().chain(
        import_map
            .scopes()
            .flat_map(|scope| scope.imports.entries()),
    ) {
        let Some(specifier) = entry.value else {
            continue;
        };
        match specifier.scheme() {
            "jsr" => {
                let specifier_str = specifier.as_str();
                let Ok(req_ref) = JsrPackageReqReference::from_str(specifier_str) else {
                    continue;
                };
                if req_ref
                    .sub_path()
                    .is_some_and(|sub_path| sub_path.ends_with('/'))
                {
                    continue;
                }
                if !seen_reqs.insert(req_ref.req().clone()) {
                    continue;
                }
                roots.push(specifier.clone());
            }
            "npm" => roots.push(specifier.clone()),
            _ => {
                if entry.key.ends_with('/') && specifier.as_str().ends_with('/') {
                    continue;
                }
                if specifier.scheme() == "file"
                    && let Ok(path) = specifier.to_file_path()
                    && !path.is_file()
                {
                    continue;
                }
                roots.push(specifier.clone());
            }
        }
    }

    Ok(roots)
}

fn is_node_modules_file_specifier(specifier: &ModuleSpecifier) -> bool {
    specifier.scheme() == "file"
        && specifier.path_segments().is_some_and(|segments| {
            segments
                .into_iter()
                .any(|segment| segment == "node_modules")
        })
}

async fn collect_graph_roots(
    context: &EmbedContext,
    extra_roots: Vec<ModuleSpecifier>,
    filter_node_modules: bool,
) -> Result<Vec<ModuleSpecifier>, AnyError> {
    let mut roots = collect_import_map_roots(context.resolver_factory()).await?;
    if filter_node_modules {
        roots.retain(|specifier| !is_node_modules_file_specifier(specifier));
    }
    roots.extend(extra_roots);
    Ok(roots)
}

pub(crate) async fn build_install_module_graph(
    context: &EmbedContext,
) -> Result<ModuleGraph, AnyError> {
    let roots = collect_graph_roots(context, context.install_graph_roots().to_vec(), true).await?;
    build_module_graph_inner(context, roots, HashMap::new()).await
}

pub(crate) async fn build_module_graph_with_header_overrides(
    context: &EmbedContext,
    extra_roots: Vec<ModuleSpecifier>,
    file_header_overrides: HashMap<ModuleSpecifier, HashMap<String, String>>,
) -> Result<ModuleGraph, AnyError> {
    let roots = collect_graph_roots(context, extra_roots, false).await?;
    build_module_graph_inner(context, roots, file_header_overrides).await
}

async fn build_module_graph_inner(
    context: &EmbedContext,
    roots: Vec<ModuleSpecifier>,
    file_header_overrides: HashMap<ModuleSpecifier, HashMap<String, String>>,
) -> Result<ModuleGraph, AnyError> {
    let resolver_factory = context.resolver_factory();
    let npm_installer_factory = context.npm_installer_factory();

    let mut graph = ModuleGraph::new(GraphKind::All);
    if roots.is_empty() {
        return Ok(graph);
    }

    let maybe_lockfile = npm_installer_factory.maybe_lockfile().await?;
    if let Some(lockfile) = &maybe_lockfile {
        lockfile.fill_graph(&mut graph);
    }
    let mut locker = maybe_lockfile
        .as_ref()
        .map(|lockfile| lockfile.as_deno_graph_locker());

    let deno_resolver = resolver_factory.deno_resolver().await?;
    let cjs_tracker = resolver_factory.cjs_tracker()?;
    let compiler_options_resolver = resolver_factory.compiler_options_resolver()?;
    let jsx_import_source_config_resolver =
        JsxImportSourceConfigResolver::from_compiler_options_resolver(compiler_options_resolver)?;
    let graph_resolver = deno_resolver.as_graph_resolver(
        cjs_tracker,
        &jsx_import_source_config_resolver,
        None,
        NpmTypesResolutionMode::Strict,
    );
    let npm_graph_resolver = npm_installer_factory
        .npm_deno_graph_resolver()
        .await?
        .as_ref();
    let jsr_version_resolver = resolver_factory.jsr_version_resolver()?;
    let jsr_url_provider = deno_graph::source::DefaultJsrUrlProvider;
    let graph_loader = context.graph_loader();
    let mut graph_loader = graph_loader.lock().await;
    for (specifier, headers) in file_header_overrides {
        graph_loader.insert_file_header_override(specifier, headers);
    }
    graph
        .build(
            roots,
            Vec::new(),
            &*graph_loader,
            deno_graph::BuildOptions {
                jsr_url_provider: &jsr_url_provider,
                jsr_version_resolver: std::borrow::Cow::Borrowed(jsr_version_resolver),
                npm_resolver: Some(npm_graph_resolver),
                resolver: Some(&graph_resolver),
                unstable_bytes_imports: context.enable_raw_imports(),
                unstable_text_imports: true,
                unstable_css_imports: context.enable_raw_imports(),
                file_system: resolver_factory.workspace_factory().sys(),
                locker: locker.as_mut().map(|locker| locker as _),
                ..Default::default()
            },
        )
        .await;
    validate_graph(context, &graph)?;
    Ok(graph)
}

fn validate_graph(context: &EmbedContext, graph: &ModuleGraph) -> Result<(), AnyError> {
    let allow_json_without_attribute =
        matches!(context.allow_json_imports(), AllowJsonImports::Always);
    let mut errors = graph
        .walk(
            graph.roots.iter(),
            WalkOptions {
                check_js: CheckJsOption::True,
                kind: GraphKind::CodeOnly,
                follow_dynamic: false,
                prefer_fast_check_graph: false,
            },
        )
        .errors()
        .filter(|error| !(allow_json_without_attribute && is_unsupported_json_media_type(error)));
    match errors.next() {
        Some(error) => Err(error.into()),
        None => Ok(()),
    }
}

fn is_unsupported_json_media_type(error: &ModuleGraphError) -> bool {
    matches!(
        error.as_module_error_kind(),
        Some(ModuleErrorKind::UnsupportedMediaType {
            media_type: MediaType::Json,
            ..
        })
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embed::{EmbedContext, EmbedContextOptions};
    use crate::packages::{dependencies_from_mapping, specified_import_map};
    use std::collections::BTreeMap;
    use std::fs;

    #[tokio::test]
    async fn collects_roots_from_specified_import_map_without_config_file() {
        let temp_dir = tempfile::tempdir().unwrap();
        let cwd = temp_dir.path().join("project");
        fs::create_dir_all(&cwd).unwrap();
        let dependencies = dependencies_from_mapping(
            &cwd,
            BTreeMap::from([("std_path".to_string(), "jsr:@std/path@^1".to_string())]),
        )
        .unwrap();
        let import_map_base = deno_core::url::Url::from_directory_path(&cwd).unwrap();
        let context = EmbedContext::new(
            cwd.clone(),
            temp_dir.path().join("deno.lock"),
            EmbedContextOptions {
                specified_import_map: Some(
                    specified_import_map(import_map_base, &dependencies).unwrap(),
                ),
                ..Default::default()
            },
        )
        .unwrap();
        let roots = collect_import_map_roots(context.resolver_factory())
            .await
            .unwrap();
        assert_eq!(roots.len(), 1);
        assert!(
            roots[0].as_str().contains("@std/path"),
            "unexpected import map root: {}",
            roots[0]
        );
    }
}
