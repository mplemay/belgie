use std::collections::HashMap;
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use deno_core::error::AnyError;
use deno_core::url::Url;
use deno_graph::GraphKind;
use deno_graph::ModuleGraph;
use deno_graph::ModuleSpecifier;
use deno_npm_installer::PackageCaching;
use deno_resolver::factory::ResolverFactory;
use deno_resolver::graph::DefaultDenoResolverRc;
use deno_resolver::loader::AllowJsonImports;
use deno_resolver::loader::ModuleLoaderRc;

use crate::embed::context::EmbedContext;
use crate::embed::graph::build_module_graph_with_header_overrides;
use crate::embed::sys::EmbedSys;

pub(crate) struct PackageRuntimeState {
    pub graph: Arc<Mutex<ModuleGraph>>,
    pub resolver_factory: Arc<ResolverFactory<EmbedSys>>,
    pub deno_resolver: DefaultDenoResolverRc<EmbedSys>,
    pub memory_files: deno_resolver::loader::MemoryFilesRc,
    pub module_loader: ModuleLoaderRc<EmbedSys>,
    pub allow_json_imports: AllowJsonImports,
}

impl PackageRuntimeState {
    pub(crate) fn with_empty_graph(&self) -> Self {
        Self {
            graph: Arc::new(Mutex::new(ModuleGraph::new(GraphKind::All))),
            resolver_factory: self.resolver_factory.clone(),
            deno_resolver: self.deno_resolver.clone(),
            memory_files: self.memory_files.clone(),
            module_loader: self.module_loader.clone(),
            allow_json_imports: self.allow_json_imports,
        }
    }
}

impl std::fmt::Debug for PackageRuntimeState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PackageRuntimeState")
            .finish_non_exhaustive()
    }
}

pub(crate) async fn prepare_package_runtime(
    context: Rc<EmbedContext>,
    main_module: ModuleSpecifier,
    main_source: Option<String>,
    file_header_overrides: HashMap<ModuleSpecifier, HashMap<String, String>>,
) -> Result<PackageRuntimeState, AnyError> {
    if let Some(main_source) = main_source {
        context.insert_memory_file(Url::parse(main_module.as_str())?, main_source);
    }

    let npm_installer_factory = context.npm_installer_factory();
    npm_installer_factory
        .initialize_npm_resolution_if_managed()
        .await?;

    let graph = build_module_graph_with_header_overrides(
        &context,
        vec![main_module],
        file_header_overrides,
    )
    .await?;
    npm_installer_factory
        .npm_installer()
        .await?
        .cache_packages(PackageCaching::All)
        .await?;
    if let Some(lockfile) = npm_installer_factory.maybe_lockfile().await? {
        if context.frozen_lockfile() {
            lockfile.error_if_changed()?;
        } else {
            lockfile.write_if_changed()?;
        }
    }
    let resolver_factory = context.resolver_factory();
    let deno_resolver = resolver_factory.deno_resolver().await?.clone();
    let memory_files = context.memory_files().clone();
    let module_loader = resolver_factory.module_loader()?.clone();

    Ok(PackageRuntimeState {
        graph: Arc::new(Mutex::new(graph)),
        resolver_factory: resolver_factory.clone(),
        deno_resolver,
        memory_files,
        module_loader,
        allow_json_imports: context.allow_json_imports(),
    })
}

pub(crate) fn js_content_type_header_overrides(
    main_module: ModuleSpecifier,
) -> HashMap<ModuleSpecifier, HashMap<String, String>> {
    HashMap::from([(
        main_module,
        HashMap::from([("content-type".to_string(), "text/javascript".to_string())]),
    )])
}
