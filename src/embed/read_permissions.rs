use std::borrow::Cow;
use std::path::Path;
use std::sync::Arc;

use deno_cache_dir::file_fetcher::MemoryFiles as _;
use deno_core::error::AnyError;
use deno_core::url::Url;
use deno_error::JsErrorBox;
use deno_lib::npm::{NpmRegistryReadPermissionChecker, NpmRegistryReadPermissionCheckerMode};
use deno_resolver::factory::ResolverFactory;
use deno_resolver::loader::MemoryFilesRc;
use deno_runtime::deno_permissions::{OpenAccessKind, PermissionsContainer};

use crate::embed::sys::EmbedSys;

#[derive(Clone, Debug)]
pub(crate) struct ModuleReadChecker {
    memory_files: MemoryFilesRc,
    npm_registries: Vec<ScopedNpmRegistryReadPermissionChecker>,
}

#[derive(Clone, Debug)]
struct ScopedNpmRegistryReadPermissionChecker {
    scope: NpmReadScope,
    checker: Arc<NpmRegistryReadPermissionChecker<EmbedSys>>,
}

#[derive(Clone, Debug)]
enum NpmReadScope {
    Byonm,
    Root(std::path::PathBuf),
}

impl NpmReadScope {
    fn contains(&self, path: &Path) -> bool {
        match self {
            Self::Byonm => path
                .components()
                .any(|component| component.as_os_str() == "node_modules"),
            Self::Root(root) => path.starts_with(root),
        }
    }
}

impl ModuleReadChecker {
    pub(crate) fn new(
        memory_files: MemoryFilesRc,
        resolver_factory: &ResolverFactory<EmbedSys>,
    ) -> Result<Self, AnyError> {
        let npm_registries = if resolver_factory.workspace_factory().no_npm() {
            Vec::new()
        } else {
            let (scope, mode) = if resolver_factory.use_byonm()? {
                (
                    NpmReadScope::Byonm,
                    NpmRegistryReadPermissionCheckerMode::Byonm,
                )
            } else if let Some(root) = resolver_factory
                .workspace_factory()
                .node_modules_dir_path()?
            {
                let root = root.to_path_buf();
                (
                    NpmReadScope::Root(root.clone()),
                    NpmRegistryReadPermissionCheckerMode::Local(root),
                )
            } else {
                let managed_resolver = resolver_factory
                    .npm_resolver()?
                    .as_managed()
                    .expect("non-BYONM resolver should be managed");
                let root = managed_resolver.global_cache_root_path().to_path_buf();
                (
                    NpmReadScope::Root(root.clone()),
                    NpmRegistryReadPermissionCheckerMode::Global(root),
                )
            };
            let mut checkers = vec![ScopedNpmRegistryReadPermissionChecker {
                scope,
                checker: Arc::new(NpmRegistryReadPermissionChecker::new(
                    EmbedSys::default(),
                    mode,
                )),
            }];
            if let Some(node_modules_dir) = resolver_factory
                .workspace_factory()
                .node_modules_dir_path()?
            {
                let workspace_node_modules = resolver_factory
                    .workspace_factory()
                    .initial_cwd()
                    .join("node_modules");
                if workspace_node_modules != node_modules_dir {
                    checkers.push(ScopedNpmRegistryReadPermissionChecker {
                        scope: NpmReadScope::Root(workspace_node_modules.clone()),
                        checker: Arc::new(NpmRegistryReadPermissionChecker::new(
                            EmbedSys::default(),
                            NpmRegistryReadPermissionCheckerMode::Local(workspace_node_modules),
                        )),
                    });
                }
            }
            checkers
        };
        Ok(Self {
            memory_files,
            npm_registries,
        })
    }

    pub(crate) fn ensure_specifier(
        &self,
        permissions: &PermissionsContainer,
        specifier: &Url,
    ) -> Result<Url, JsErrorBox> {
        if specifier.scheme() != "file" || self.memory_files.get(specifier).is_some() {
            return Ok(specifier.clone());
        }
        let path = specifier.to_file_path().map_err(|()| {
            JsErrorBox::generic(format!("Could not convert {specifier} to a file path"))
        })?;
        let checked_path = self.ensure_path(permissions, Cow::Owned(path))?;
        deno_path_util::url_from_file_path(checked_path.as_ref()).map_err(JsErrorBox::from_err)
    }

    pub(crate) fn ensure_path<'a>(
        &self,
        permissions: &PermissionsContainer,
        path: Cow<'a, Path>,
    ) -> Result<Cow<'a, Path>, JsErrorBox> {
        if let Ok(specifier) = deno_path_util::url_from_file_path(&path)
            && self.memory_files.get(&specifier).is_some()
        {
            return Ok(path);
        }
        if let Some(npm_registry) = self
            .npm_registries
            .iter()
            .find(|registry| registry.scope.contains(&path))
        {
            let mut permissions = permissions.clone();
            return npm_registry
                .checker
                .ensure_read_permission(&mut permissions, path);
        }
        permissions
            .check_open(path, OpenAccessKind::Read, Some("module load"))
            .map(|checked_path| checked_path.into_path())
            .map_err(JsErrorBox::from_err)
    }
}
