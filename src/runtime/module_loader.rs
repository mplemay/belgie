use std::{borrow::Cow, fs, future::Future, path::PathBuf, pin::Pin, sync::Arc};

use deno_ast::{MediaType, ParseParams, SourceMapOption};
use deno_cache_dir::file_fetcher::MemoryFiles as _;
use deno_core::{
    ModuleLoadOptions, ModuleLoadReferrer, ModuleLoadResponse, ModuleLoader, ModuleSource,
    ModuleSourceCode, ModuleSpecifier, ModuleType, RequestedModuleType, ResolutionKind,
    error::ModuleLoaderError,
};
use deno_error::JsErrorBox;
use deno_graph::Position;
use deno_lib::loader::as_deno_resolver_requested_module_type;
use deno_lib::loader::loaded_module_source_to_module_source_code;
use deno_lib::loader::module_type_from_media_and_requested_type;
use deno_resolver::graph::ResolveWithGraphOptions;
use deno_resolver::loader::LoadedModule;
use deno_resolver::loader::LoadedModuleOrAsset;
use deno_semver::npm::NpmPackageReqReference;
use futures::FutureExt;
use node_resolver::NodeResolutionKind;
use node_resolver::ResolutionMode;
use url::Url;

use crate::embed::PackageRuntimeState;
use crate::embed::insert_memory_file;

#[derive(Debug, Default)]
pub(crate) struct PythonModuleLoader;

impl ModuleLoader for PythonModuleLoader {
    fn resolve(
        &self,
        specifier: &str,
        referrer: &str,
        _kind: ResolutionKind,
    ) -> Result<ModuleSpecifier, ModuleLoaderError> {
        deno_core::resolve_import(specifier, referrer).map_err(JsErrorBox::from_err)
    }

    fn load(
        &self,
        module_specifier: &ModuleSpecifier,
        _maybe_referrer: Option<&ModuleLoadReferrer>,
        options: ModuleLoadOptions,
    ) -> ModuleLoadResponse {
        ModuleLoadResponse::Sync(load_module_source(
            module_specifier,
            options.requested_module_type,
        ))
    }
}

fn load_module_source(
    module_specifier: &ModuleSpecifier,
    requested_module_type: RequestedModuleType,
) -> Result<ModuleSource, ModuleLoaderError> {
    load_module_source_with_media_type(module_specifier, requested_module_type, None)
}

fn load_module_source_with_media_type(
    module_specifier: &ModuleSpecifier,
    requested_module_type: RequestedModuleType,
    media_type_override: Option<MediaType>,
) -> Result<ModuleSource, ModuleLoaderError> {
    let path = module_specifier
        .to_file_path()
        .map_err(|_| JsErrorBox::generic("Only file:// URLs are supported."))?;

    if matches!(
        requested_module_type,
        RequestedModuleType::Bytes | RequestedModuleType::Text | RequestedModuleType::Other(_)
    ) {
        let bytes = read_bytes(&path, module_specifier)?;
        return Ok(ModuleSource::new(
            match requested_module_type {
                RequestedModuleType::Bytes => ModuleType::Bytes,
                RequestedModuleType::Text => ModuleType::Text,
                RequestedModuleType::Other(module_type) => ModuleType::Other(module_type),
                _ => unreachable!(),
            },
            ModuleSourceCode::Bytes(bytes.into_boxed_slice().into()),
            module_specifier,
            None,
        ));
    }

    let media_type = media_type_override.unwrap_or_else(|| MediaType::from_path(&path));
    let (module_type, should_transpile) = module_type_for_media_type(media_type, &path)?;
    if module_type == ModuleType::Json && requested_module_type != RequestedModuleType::Json {
        return Err(JsErrorBox::generic(
            "Attempted to load JSON module without specifying \"type\": \"json\" attribute in the import statement.",
        ));
    }

    let code = if should_transpile {
        ModuleSourceCode::String(transpile_module(module_specifier, &path, media_type)?.into())
    } else {
        ModuleSourceCode::Bytes(
            read_bytes(&path, module_specifier)?
                .into_boxed_slice()
                .into(),
        )
    };
    Ok(ModuleSource::new(module_type, code, module_specifier, None))
}

pub(crate) fn maybe_transpile_source(
    module_specifier: &ModuleSpecifier,
    source: String,
) -> Result<String, ModuleLoaderError> {
    let path = module_specifier
        .to_file_path()
        .map_err(|_| JsErrorBox::generic("Only file:// URLs are supported."))?;
    let media_type = MediaType::from_path(&path);
    let (module_type, should_transpile) = module_type_for_media_type(media_type, &path)?;
    if module_type != ModuleType::JavaScript {
        return Err(JsErrorBox::generic(format!(
            "Entrypoint must be JavaScript or TypeScript, got {:?}",
            path.extension()
        )));
    }
    if should_transpile {
        transpile_source(module_specifier, source, media_type)
    } else {
        Ok(source)
    }
}

fn module_type_for_media_type(
    media_type: MediaType,
    path: &std::path::Path,
) -> Result<(ModuleType, bool), ModuleLoaderError> {
    match media_type {
        MediaType::JavaScript | MediaType::Mjs | MediaType::Cjs => {
            Ok((ModuleType::JavaScript, false))
        }
        MediaType::Jsx
        | MediaType::TypeScript
        | MediaType::Mts
        | MediaType::Cts
        | MediaType::Dts
        | MediaType::Dmts
        | MediaType::Dcts
        | MediaType::Tsx => Ok((ModuleType::JavaScript, true)),
        MediaType::Json => Ok((ModuleType::Json, false)),
        MediaType::Wasm => Ok((ModuleType::Wasm, false)),
        _ => Err(JsErrorBox::generic(format!(
            "Unknown extension {:?}",
            path.extension()
        ))),
    }
}

fn read_bytes(
    path: &std::path::Path,
    module_specifier: &ModuleSpecifier,
) -> Result<Vec<u8>, ModuleLoaderError> {
    fs::read(path)
        .map_err(|error| JsErrorBox::generic(format!("Failed to load {module_specifier}: {error}")))
}

fn transpile_module(
    module_specifier: &ModuleSpecifier,
    path: &std::path::Path,
    media_type: MediaType,
) -> Result<String, ModuleLoaderError> {
    let source = fs::read_to_string(path).map_err(|error| {
        JsErrorBox::generic(format!("Failed to load {module_specifier}: {error}"))
    })?;
    transpile_source(module_specifier, source, media_type)
}

fn transpile_source(
    module_specifier: &ModuleSpecifier,
    source: String,
    media_type: MediaType,
) -> Result<String, ModuleLoaderError> {
    let parsed = deno_ast::parse_module(ParseParams {
        specifier: module_specifier.clone(),
        text: source.into(),
        media_type,
        capture_tokens: false,
        scope_analysis: false,
        maybe_syntax: None,
    })
    .map_err(JsErrorBox::from_err)?;
    let transpiled = parsed
        .transpile(
            &deno_ast::TranspileOptions {
                imports_not_used_as_values: deno_ast::ImportsNotUsedAsValues::Remove,
                decorators: deno_ast::DecoratorsTranspileOption::Ecma,
                ..Default::default()
            },
            &deno_ast::TranspileModuleOptions { module_kind: None },
            &deno_ast::EmitOptions {
                source_map: SourceMapOption::None,
                ..Default::default()
            },
        )
        .map_err(JsErrorBox::from_err)?
        .into_source();
    Ok(transpiled.text)
}

#[derive(Debug)]
pub(crate) struct PackageAwareModuleLoader {
    state: Arc<PackageRuntimeState>,
    initial_cwd: PathBuf,
}

impl PackageAwareModuleLoader {
    pub(crate) fn new(state: Arc<PackageRuntimeState>, initial_cwd: PathBuf) -> Self {
        Self { state, initial_cwd }
    }

    fn resolve_referrer(&self, referrer: &str) -> Result<ModuleSpecifier, ModuleLoaderError> {
        if deno_path_util::specifier_has_uri_scheme(referrer) {
            return ModuleSpecifier::parse(referrer).map_err(JsErrorBox::from_err);
        }
        if referrer == "." {
            return deno_path_util::resolve_path(referrer, &self.initial_cwd)
                .map_err(JsErrorBox::from_err);
        }
        deno_core::resolve_import(referrer, &self.initial_cwd.to_string_lossy())
            .map_err(JsErrorBox::from_err)
    }

    fn default_referrer(&self) -> Result<ModuleSpecifier, ModuleLoaderError> {
        deno_path_util::url_from_directory_path(&self.initial_cwd).map_err(JsErrorBox::from_err)
    }

    fn resolve_inner(
        &self,
        raw_specifier: &str,
        referrer: &str,
        maintain_npm_specifiers: bool,
    ) -> Result<ModuleSpecifier, ModuleLoaderError> {
        let referrer = self.resolve_referrer(referrer)?;
        let referrer_url = Url::parse(referrer.as_str()).map_err(JsErrorBox::from_err)?;
        let node_resolver = self
            .state
            .resolver_factory
            .node_resolver()
            .map_err(|error| JsErrorBox::generic(error.to_string()))?;
        let is_npm_referrer = node_resolver.in_npm_package(&referrer);
        let resolution_mode = if is_npm_referrer {
            let cjs_tracker = self
                .state
                .resolver_factory
                .cjs_tracker()
                .map_err(|error| JsErrorBox::generic(error.to_string()))?;
            if cjs_tracker
                .is_maybe_cjs(&referrer, MediaType::from_specifier(&referrer))
                .map_err(JsErrorBox::from_err)?
            {
                ResolutionMode::Require
            } else {
                ResolutionMode::Import
            }
        } else {
            ResolutionMode::Import
        };
        if is_npm_referrer {
            let specifier = node_resolver
                .resolve(
                    raw_specifier,
                    &referrer_url,
                    resolution_mode,
                    NodeResolutionKind::Execution,
                )
                .and_then(|resolution| resolution.into_url())
                .map_err(JsErrorBox::from_err)?;
            return Ok(specifier);
        }
        let graph = self
            .state
            .graph
            .lock()
            .expect("module graph lock should not be poisoned")
            .clone();
        let specifier = self
            .state
            .deno_resolver
            .resolve_with_graph(
                &graph,
                raw_specifier,
                &referrer_url,
                Position::zeroed(),
                ResolveWithGraphOptions {
                    mode: resolution_mode,
                    kind: NodeResolutionKind::Execution,
                    maintain_npm_specifiers,
                },
            )
            .map_err(JsErrorBox::from_err)?;
        ModuleSpecifier::parse(specifier.as_str()).map_err(JsErrorBox::from_err)
    }

    fn insert_memory_module(
        &self,
        module_specifier: &ModuleSpecifier,
        source: String,
    ) -> Result<(), ModuleLoaderError> {
        let url = Url::parse(module_specifier.as_str()).map_err(JsErrorBox::from_err)?;
        insert_memory_file(&self.state.memory_files, url, source);
        Ok(())
    }

    fn load_memory_module(
        &self,
        module_specifier: &ModuleSpecifier,
        requested_module_type: RequestedModuleType,
    ) -> Result<ModuleSource, ModuleLoaderError> {
        let url = Url::parse(module_specifier.as_str()).map_err(JsErrorBox::from_err)?;
        let file = self.state.memory_files.get(&url).ok_or_else(|| {
            JsErrorBox::generic(format!("Memory module not found: {module_specifier}"))
        })?;
        let source = String::from_utf8(file.source.to_vec()).map_err(|err| {
            JsErrorBox::generic(format!(
                "Invalid UTF-8 in memory module {module_specifier}: {err}"
            ))
        })?;
        if matches!(
            requested_module_type,
            RequestedModuleType::Bytes | RequestedModuleType::Text | RequestedModuleType::Other(_)
        ) {
            return Ok(ModuleSource::new(
                match requested_module_type {
                    RequestedModuleType::Bytes => ModuleType::Bytes,
                    RequestedModuleType::Text => ModuleType::Text,
                    RequestedModuleType::Other(module_type) => ModuleType::Other(module_type),
                    _ => unreachable!(),
                },
                ModuleSourceCode::Bytes(file.source.to_vec().into_boxed_slice().into()),
                module_specifier,
                None,
            ));
        }
        let code = maybe_transpile_source(module_specifier, source)?;
        Ok(ModuleSource::new(
            ModuleType::JavaScript,
            ModuleSourceCode::String(code.into()),
            module_specifier,
            None,
        ))
    }

    async fn load_package_module(
        &self,
        module_specifier: &ModuleSpecifier,
        maybe_referrer: Option<&ModuleSpecifier>,
        requested_module_type: RequestedModuleType,
    ) -> Result<ModuleSource, ModuleLoaderError> {
        let deno_requested = as_deno_resolver_requested_module_type(&requested_module_type);
        let specifier_url = Url::parse(module_specifier.as_str()).map_err(JsErrorBox::from_err)?;
        let maybe_referrer_url = maybe_referrer
            .map(|referrer| Url::parse(referrer.as_str()).map_err(JsErrorBox::from_err))
            .transpose()?;
        let resolved_specifier =
            if let Ok(reference) = NpmPackageReqReference::from_specifier(module_specifier) {
                let referrer = match maybe_referrer {
                    Some(referrer) => Cow::Borrowed(referrer),
                    None => Cow::Owned(self.default_referrer()?),
                };
                Cow::Owned(
                    self.state
                        .deno_resolver
                        .resolve_non_workspace_npm_req_ref_to_file(
                            &reference,
                            &referrer,
                            ResolutionMode::Import,
                            NodeResolutionKind::Execution,
                        )
                        .map_err(JsErrorBox::from_err)?
                        .into_url()
                        .map_err(JsErrorBox::from_err)?,
                )
            } else {
                Cow::Borrowed(&specifier_url)
            };
        let graph = self
            .state
            .graph
            .lock()
            .expect("module graph lock should not be poisoned")
            .clone();
        let loaded = self
            .state
            .module_loader
            .load(
                &graph,
                resolved_specifier.as_ref(),
                maybe_referrer_url.as_ref(),
                &deno_requested,
            )
            .await
            .map_err(JsErrorBox::from_err)?;
        match loaded {
            LoadedModuleOrAsset::Module(loaded_module) => loaded_module_to_module_source(
                loaded_module,
                &requested_module_type,
                module_specifier,
            ),
            LoadedModuleOrAsset::ExternalAsset { specifier, .. } => Err(JsErrorBox::generic(
                format!("Unsupported external asset import: {specifier}"),
            )),
        }
    }
}

fn loaded_module_to_module_source(
    loaded_module: LoadedModule<'_>,
    requested_module_type: &RequestedModuleType,
    module_specifier: &ModuleSpecifier,
) -> Result<ModuleSource, ModuleLoaderError> {
    Ok(ModuleSource::new_with_redirect(
        module_type_from_media_and_requested_type(loaded_module.media_type, requested_module_type),
        loaded_module_source_to_module_source_code(loaded_module.source),
        module_specifier,
        &ModuleSpecifier::parse(loaded_module.specifier.as_str()).map_err(JsErrorBox::from_err)?,
        None,
    ))
}

impl ModuleLoader for PackageAwareModuleLoader {
    fn resolve(
        &self,
        specifier: &str,
        referrer: &str,
        kind: ResolutionKind,
    ) -> Result<ModuleSpecifier, ModuleLoaderError> {
        self.resolve_inner(
            specifier,
            referrer,
            matches!(kind, ResolutionKind::DynamicImport),
        )
    }

    fn load(
        &self,
        module_specifier: &ModuleSpecifier,
        maybe_referrer: Option<&ModuleLoadReferrer>,
        options: ModuleLoadOptions,
    ) -> ModuleLoadResponse {
        if self
            .state
            .memory_files
            .get(
                &Url::parse(module_specifier.as_str())
                    .expect("module specifier should be a valid URL"),
            )
            .is_some()
        {
            return ModuleLoadResponse::Sync(
                self.load_memory_module(module_specifier, options.requested_module_type),
            );
        }

        let is_npm_package = match self.state.resolver_factory.node_resolver() {
            Ok(node_resolver) => node_resolver.in_npm_package(module_specifier),
            Err(error) => {
                return ModuleLoadResponse::Sync(Err(JsErrorBox::generic(error.to_string())));
            }
        };

        if !is_npm_package
            && module_specifier.scheme() == "file"
            && module_specifier
                .to_file_path()
                .ok()
                .is_some_and(|path| path.exists())
        {
            return ModuleLoadResponse::Sync(load_module_source(
                module_specifier,
                options.requested_module_type,
            ));
        }

        let state = self.state.clone();
        let initial_cwd = self.initial_cwd.clone();
        let module_specifier = module_specifier.clone();
        let maybe_referrer = maybe_referrer.map(|referrer| referrer.specifier.clone());
        let requested_module_type = options.requested_module_type;

        ModuleLoadResponse::Async(
            async move {
                let loader = PackageAwareModuleLoader { state, initial_cwd };
                loader
                    .load_package_module(
                        &module_specifier,
                        maybe_referrer.as_ref(),
                        requested_module_type,
                    )
                    .await
            }
            .boxed_local(),
        )
    }

    fn prepare_load(
        &self,
        module_specifier: &ModuleSpecifier,
        _maybe_referrer: Option<String>,
        maybe_content: Option<String>,
        _options: ModuleLoadOptions,
    ) -> Pin<Box<dyn Future<Output = Result<(), ModuleLoaderError>>>> {
        let result = if let Some(source) = maybe_content {
            self.insert_memory_module(module_specifier, source)
        } else {
            Ok(())
        };
        async move { result }.boxed_local()
    }
}

#[cfg(test)]
mod tests {
    use super::load_module_source;
    use deno_core::{ModuleSourceCode, ModuleSpecifier, ModuleType, RequestedModuleType};
    use std::{
        fs, io,
        path::{Path, PathBuf},
        time::{SystemTime, UNIX_EPOCH},
    };

    fn temp_dir(name: &str) -> io::Result<PathBuf> {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock should be after the Unix epoch")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "belgie-module-loader-{name}-{}-{nanos}",
            std::process::id()
        ));
        fs::create_dir_all(&path)?;
        Ok(path)
    }

    fn specifier(path: &Path) -> ModuleSpecifier {
        ModuleSpecifier::from_file_path(path).expect("path should convert to file URL")
    }

    #[test]
    fn transpiles_typescript_modules_loaded_from_files() {
        let root = temp_dir("typescript").expect("temp dir should be created");
        let path = root.join("dep.ts");
        fs::write(
            &path,
            "export function double(value: number): number { return value * 2; }\n",
        )
        .expect("typescript module should be written");

        let module = load_module_source(&specifier(&path), RequestedModuleType::None)
            .expect("typescript module should load");

        let _ = fs::remove_dir_all(&root);
        assert_eq!(module.module_type, ModuleType::JavaScript);
        let ModuleSourceCode::String(code) = module.code else {
            panic!("typescript modules should be loaded as transpiled string source");
        };
        assert!(!code.as_str().contains(": number"));
    }

    #[test]
    fn rejects_json_imports_without_json_import_attribute() {
        let root = temp_dir("json").expect("temp dir should be created");
        let path = root.join("data.json");
        fs::write(&path, "{\"answer\":42}").expect("json module should be written");

        let result = load_module_source(&specifier(&path), RequestedModuleType::None);

        let _ = fs::remove_dir_all(&root);
        assert!(result.is_err());
    }
}
