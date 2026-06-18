use std::rc::Rc;
use std::sync::Mutex;

use deno_core::error::AnyError;
use deno_core::url::Url;
use deno_graph::ModuleGraph;
use deno_graph::ModuleSpecifier;
use deno_resolver::graph::DefaultDenoResolverRc;
use deno_resolver::loader::ModuleLoaderRc;

use crate::embed::context::EmbedContext;
use crate::embed::graph::build_module_graph;
use crate::embed::sys::EmbedSys;

pub(crate) struct PackageRuntimeState {
    pub context: Rc<EmbedContext>,
    pub graph: Rc<Mutex<ModuleGraph>>,
    pub deno_resolver: DefaultDenoResolverRc<EmbedSys>,
    pub module_loader: ModuleLoaderRc<EmbedSys>,
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
    main_source: String,
) -> Result<PackageRuntimeState, AnyError> {
    let npm_installer_factory = context.npm_installer_factory();
    npm_installer_factory
        .initialize_npm_resolution_if_managed()
        .await?;

    let main_url = Url::parse(main_module.as_str())?;
    context.insert_memory_file(main_url, main_source);

    let graph = build_module_graph(&context, vec![main_module]).await?;
    if let Some(lockfile) = npm_installer_factory.maybe_lockfile().await? {
        lockfile.error_if_changed()?;
    }
    let resolver_factory = context.resolver_factory();
    let deno_resolver = resolver_factory.deno_resolver().await?.clone();
    let module_loader = resolver_factory.module_loader()?.clone();

    Ok(PackageRuntimeState {
        context,
        graph: Rc::new(Mutex::new(graph)),
        deno_resolver,
        module_loader,
    })
}
