use std::path::PathBuf;
use std::rc::Rc;

use deno_core::error::AnyError;
use deno_npm_installer::PackageCaching;

use crate::embed::context::{EmbedContext, EmbedContextOptions};
use crate::embed::graph::build_module_graph;

pub(crate) async fn install_packages_with_options(
    cwd: PathBuf,
    config_file: PathBuf,
    lockfile: PathBuf,
    lockfile_only: bool,
    options: EmbedContextOptions,
) -> Result<Rc<EmbedContext>, AnyError> {
    let context = Rc::new(EmbedContext::new_with_options(
        cwd,
        config_file,
        lockfile,
        options,
    )?);
    let npm_installer_factory = context.npm_installer_factory();
    npm_installer_factory
        .initialize_npm_resolution_if_managed()
        .await?;
    let npm_installer = npm_installer_factory.npm_installer().await?;
    npm_installer.ensure_no_pkg_json_dep_errors()?;
    npm_installer
        .ensure_top_level_package_json_install()
        .await?;

    if let Some(lockfile) = npm_installer_factory.maybe_lockfile().await? {
        lockfile.error_if_changed()?;
    }

    build_module_graph(context.as_ref(), Vec::new()).await?;

    if lockfile_only {
        npm_installer.install_resolution_if_pending().await?;
    } else {
        npm_installer.cache_packages(PackageCaching::All).await?;
    }

    if let Some(lockfile) = npm_installer_factory.maybe_lockfile().await? {
        lockfile.write_if_changed()?;
    }

    Ok(context)
}
