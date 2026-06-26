use std::collections::HashMap;
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::Arc;

use deno_cache_dir::file_fetcher::CacheSetting;
use deno_cache_dir::file_fetcher::NullBlobStore;
use deno_cache_dir::file_fetcher::SendError;
use deno_cache_dir::file_fetcher::SendResponse;
use deno_config::deno_json::{NodeModulesDirMode, NodeModulesLinkerMode};
use deno_core::error::AnyError;
use deno_core::url::Url;
use deno_error::JsErrorBox;
use deno_graph::ModuleSpecifier;
use deno_lib::args::get_root_cert_store;
use deno_lib::version::DENO_VERSION_INFO;
use deno_npm_cache::NpmCacheHttpClient;
use deno_npm_cache::NpmCacheHttpClientBytesResponse;
use deno_npm_cache::NpmCacheHttpClientResponse;
use deno_npm_cache::NpmCacheSetting;
use deno_npm_installer::LogReporter;
use deno_npm_installer::NpmInstallerFactory;
use deno_npm_installer::NpmInstallerFactoryOptions;
use deno_npm_installer::graph::NpmCachingStrategy;
use deno_npm_installer::lifecycle_scripts::NullLifecycleScriptsExecutor;
use deno_npmrc::RegistryConfig;
use deno_resolver::factory::ConfigDiscoveryOption;
use deno_resolver::factory::ResolverFactory;
use deno_resolver::factory::ResolverFactoryOptions;
use deno_resolver::factory::SpecifiedImportMapProvider;
use deno_resolver::factory::WorkspaceFactory;
use deno_resolver::factory::WorkspaceFactoryOptions;
use deno_resolver::file_fetcher::DenoGraphLoader;
use deno_resolver::file_fetcher::DenoGraphLoaderOptions;
use deno_resolver::file_fetcher::PermissionedFileFetcher;
use deno_resolver::file_fetcher::PermissionedFileFetcherOptions;
use deno_resolver::loader::AllowJsonImports;
use deno_resolver::loader::MemoryFiles;
use deno_resolver::workspace::SpecifiedImportMap;
use deno_runtime::deno_fetch;
use deno_runtime::deno_fetch::CreateHttpClientOptions;
use deno_runtime::deno_fetch::create_http_client;
use deno_runtime::deno_tls::rustls::RootCertStore;
use http::HeaderMap;
use http::StatusCode;
use http_body_util::BodyExt;
use tokio::sync::Mutex;

use crate::embed::init::ensure_initialized;
use crate::embed::memory;
use crate::embed::sys::EmbedSys;

#[derive(Debug, Clone)]
pub(crate) struct EmbedHttpClient {
    inner: deno_fetch::Client,
}

impl EmbedHttpClient {
    fn new(
        root_cert_store: RootCertStore,
        unsafely_ignore_certificate_errors: Option<Vec<String>>,
    ) -> Result<Self, AnyError> {
        let client = create_http_client(
            DENO_VERSION_INFO.user_agent,
            CreateHttpClientOptions {
                root_cert_store: Some(root_cert_store),
                unsafely_ignore_certificate_errors,
                ..Default::default()
            },
        )
        .map_err(JsErrorBox::from_err)?;
        Ok(Self { inner: client })
    }

    pub(crate) async fn fetch_bytes(&self, url: &Url) -> Result<Vec<u8>, JsErrorBox> {
        let (status, _, body) = self.send_no_follow_inner(url, HeaderMap::new()).await?;
        if !status.is_success() {
            return Err(JsErrorBox::generic(format!("HTTP status {status}")));
        }
        Ok(body)
    }

    async fn send_no_follow_inner(
        &self,
        url: &Url,
        headers: HeaderMap,
    ) -> Result<(StatusCode, HeaderMap, Vec<u8>), JsErrorBox> {
        let body = deno_fetch::ReqBody::empty();
        let mut request = http::Request::new(body);
        *request.uri_mut() = http::Uri::try_from(url.as_str())
            .map_err(|err| JsErrorBox::generic(err.to_string()))?;
        *request.method_mut() = http::Method::GET;
        *request.headers_mut() = headers;
        let response = self
            .inner
            .clone()
            .send(request)
            .await
            .map_err(JsErrorBox::from_err)?;
        let status = response.status();
        let headers = response.headers().clone();
        let body = response
            .into_body()
            .collect()
            .await
            .map_err(JsErrorBox::from_err)?
            .to_bytes();
        Ok((status, headers, body.to_vec()))
    }
}

#[async_trait::async_trait(?Send)]
impl deno_cache_dir::file_fetcher::HttpClient for EmbedHttpClient {
    async fn send_no_follow(
        &self,
        url: &Url,
        headers: HeaderMap,
    ) -> Result<SendResponse, SendError> {
        let (status, headers, body) = self
            .send_no_follow_inner(url, headers)
            .await
            .map_err(|err| SendError::Failed(err.into()))?;
        if status == StatusCode::NOT_MODIFIED {
            return Ok(SendResponse::NotModified);
        }
        if status.is_redirection() {
            return Ok(SendResponse::Redirect(headers));
        }
        if status == StatusCode::NOT_FOUND {
            return Err(SendError::NotFound);
        }
        if !status.is_success() {
            return Err(SendError::StatusCode(status));
        }
        Ok(SendResponse::Success(headers, body))
    }
}

#[async_trait::async_trait(?Send)]
impl NpmCacheHttpClient for EmbedHttpClient {
    async fn download_with_retries_on_any_tokio_runtime(
        &self,
        url: Url,
        maybe_auth: Option<String>,
        maybe_etag: Option<String>,
        _maybe_registry_config: Option<&RegistryConfig>,
    ) -> Result<NpmCacheHttpClientResponse, deno_npm_cache::DownloadError> {
        let mut headers = HeaderMap::new();
        if let Some(auth) = maybe_auth {
            headers.insert(
                http::header::AUTHORIZATION,
                http::HeaderValue::try_from(auth).unwrap(),
            );
        }
        if let Some(etag) = maybe_etag {
            headers.insert(
                http::header::IF_NONE_MATCH,
                http::HeaderValue::try_from(etag).unwrap(),
            );
        }
        headers.insert(
            http::header::ACCEPT,
            http::HeaderValue::from_static(
                "application/vnd.npm.install-v1+json; q=1.0, application/json; q=0.8, */*",
            ),
        );
        let (status, headers, body) =
            self.send_no_follow_inner(&url, headers)
                .await
                .map_err(|error| deno_npm_cache::DownloadError {
                    status_code: None,
                    error,
                })?;
        match status {
            StatusCode::NOT_FOUND => Ok(NpmCacheHttpClientResponse::NotFound),
            StatusCode::NOT_MODIFIED => Ok(NpmCacheHttpClientResponse::NotModified),
            status if status.is_success() => Ok(NpmCacheHttpClientResponse::Bytes(
                NpmCacheHttpClientBytesResponse {
                    etag: headers
                        .get(http::header::ETAG)
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_string),
                    bytes: body,
                },
            )),
            status => Err(deno_npm_cache::DownloadError {
                status_code: Some(status.as_u16()),
                error: JsErrorBox::generic(format!("HTTP status {status}")),
            }),
        }
    }
}

pub(crate) struct EmbedContext {
    pub cwd: PathBuf,
    pub lockfile: PathBuf,
    http_client: Arc<EmbedHttpClient>,
    resolver_factory: Arc<ResolverFactory<EmbedSys>>,
    npm_installer_factory: Rc<NpmInstallerFactory<EmbedHttpClient, LogReporter, EmbedSys>>,
    memory_files: deno_resolver::loader::MemoryFilesRc,
    graph_loader: Mutex<DenoGraphLoader<NullBlobStore, EmbedSys, EmbedHttpClient>>,
    install_graph_roots: Vec<ModuleSpecifier>,
    allow_json_imports: AllowJsonImports,
    enable_raw_imports: bool,
    frozen_lockfile: bool,
    unsafely_ignore_certificate_errors: Option<Vec<String>>,
}

#[derive(Clone, Debug)]
pub(crate) struct EmbedContextOptions {
    pub cache: Option<PathBuf>,
    pub cache_setting: CacheSetting,
    pub allow_remote: bool,
    pub allow_json_imports: AllowJsonImports,
    pub enable_raw_imports: bool,
    pub frozen_lockfile: Option<bool>,
    pub is_package_manager_subcommand: bool,
    pub lockfile_skip_write: bool,
    pub node_modules_dir_mode: Option<NodeModulesDirMode>,
    pub node_modules_linker: Option<NodeModulesLinkerMode>,
    pub node_modules_root: Option<PathBuf>,
    pub no_npm: bool,
    pub import_package_lockfile: bool,
    pub npm_caching: NpmCachingStrategy,
    pub clean_on_install: bool,
    pub production: bool,
    pub skip_types: bool,
    pub newest_dependency_date: Option<deno_config::deno_json::NewestDependencyDate>,
    pub unsafely_ignore_certificate_errors: Option<Vec<String>>,
    pub specified_import_map: Option<SpecifiedImportMap>,
    pub install_graph_roots: Vec<ModuleSpecifier>,
}

impl Default for EmbedContextOptions {
    fn default() -> Self {
        Self {
            cache: None,
            cache_setting: CacheSetting::Use,
            allow_remote: true,
            allow_json_imports: AllowJsonImports::WithAttribute,
            enable_raw_imports: false,
            frozen_lockfile: None,
            is_package_manager_subcommand: false,
            lockfile_skip_write: false,
            node_modules_dir_mode: None,
            node_modules_linker: None,
            node_modules_root: None,
            no_npm: false,
            import_package_lockfile: false,
            npm_caching: NpmCachingStrategy::Eager,
            clean_on_install: true,
            production: false,
            skip_types: false,
            newest_dependency_date: None,
            unsafely_ignore_certificate_errors: None,
            specified_import_map: None,
            install_graph_roots: Vec::new(),
        }
    }
}

impl EmbedContextOptions {
    pub(crate) fn for_package_manager(mut self) -> Self {
        self.is_package_manager_subcommand = true;
        self
    }

    pub(crate) fn requires_embed_module_loader(&self) -> bool {
        !self.allow_remote
            || !matches!(self.allow_json_imports, AllowJsonImports::WithAttribute)
            || self.no_npm
            || self.unsafely_ignore_certificate_errors.is_some()
            || self.cache_setting != CacheSetting::Use
    }
}

impl std::fmt::Debug for EmbedContext {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EmbedContext")
            .field("cwd", &self.cwd)
            .field("lockfile", &self.lockfile)
            .finish_non_exhaustive()
    }
}

#[derive(Debug)]
struct StaticImportMapProvider {
    import_map: SpecifiedImportMap,
}

#[async_trait::async_trait(?Send)]
impl SpecifiedImportMapProvider for StaticImportMapProvider {
    async fn get(&self) -> Result<Option<SpecifiedImportMap>, AnyError> {
        Ok(Some(self.import_map.clone()))
    }
}

impl EmbedContext {
    #[cfg(test)]
    pub fn new(
        cwd: PathBuf,
        lockfile: PathBuf,
        options: EmbedContextOptions,
    ) -> Result<Self, AnyError> {
        Self::new_with_options(cwd, lockfile, options)
    }

    pub fn new_with_options(
        cwd: PathBuf,
        lockfile: PathBuf,
        options: EmbedContextOptions,
    ) -> Result<Self, AnyError> {
        ensure_initialized();
        let sys = EmbedSys::default();
        let lockfile = if lockfile.is_absolute() {
            lockfile
        } else {
            cwd.join(lockfile)
        };
        let node_modules_dir = options.node_modules_dir_mode.unwrap_or_else(|| {
            if options.node_modules_root.is_some() {
                NodeModulesDirMode::Auto
            } else {
                NodeModulesDirMode::None
            }
        });

        let workspace_factory = Arc::new(WorkspaceFactory::new(
            sys.clone(),
            cwd.clone(),
            WorkspaceFactoryOptions {
                config_discovery: ConfigDiscoveryOption::Disabled,
                lock_arg: Some(lockfile.clone()),
                is_package_manager_subcommand: options.is_package_manager_subcommand,
                frozen_lockfile: options.frozen_lockfile,
                lockfile_skip_write: options.lockfile_skip_write,
                maybe_custom_deno_dir_root: options.cache,
                node_modules_dir: Some(node_modules_dir),
                node_modules_linker: options.node_modules_linker,
                no_npm: options.no_npm,
                import_npm_lockfile: options.import_package_lockfile,
                root_node_modules_dir_override: options.node_modules_root,
                ..Default::default()
            },
        ));

        let resolver_factory = Arc::new(ResolverFactory::new(
            workspace_factory,
            ResolverFactoryOptions {
                allow_json_imports: options.allow_json_imports,
                newest_dependency_date: options.newest_dependency_date,
                specified_import_map: options.specified_import_map.map(|import_map| {
                    Box::new(StaticImportMapProvider { import_map })
                        as Box<dyn SpecifiedImportMapProvider>
                }),
                ..Default::default()
            },
        ));

        let root_cert_store = get_root_cert_store(&sys, None, None, None)?;
        let http_client = Arc::new(EmbedHttpClient::new(
            root_cert_store,
            options.unsafely_ignore_certificate_errors.clone(),
        )?);
        let memory_files = deno_maybe_sync::new_rc(MemoryFiles::default());
        let global_http_cache = resolver_factory
            .workspace_factory()
            .global_http_cache()
            .map_err(AnyError::from)?
            .clone();
        let file_fetcher = deno_maybe_sync::new_rc(PermissionedFileFetcher::new(
            NullBlobStore,
            deno_maybe_sync::new_rc(deno_cache_dir::GlobalOrLocalHttpCache::from(
                global_http_cache.clone(),
            )),
            http_client.as_ref().clone(),
            memory_files.clone(),
            sys.clone(),
            PermissionedFileFetcherOptions {
                allow_remote: options.allow_remote,
                cache_setting: options.cache_setting.clone(),
            },
        ));
        let graph_loader = DenoGraphLoader::new(
            file_fetcher,
            global_http_cache,
            resolver_factory.in_npm_package_checker()?.clone(),
            sys.clone(),
            DenoGraphLoaderOptions {
                file_header_overrides: HashMap::new(),
                permissions: None,
                reporter: None,
                include_npm_sources: !options.no_npm,
            },
        );

        let npm_installer_factory = Rc::new(NpmInstallerFactory::new(
            resolver_factory.clone(),
            http_client.clone(),
            Arc::new(NullLifecycleScriptsExecutor),
            LogReporter,
            None,
            NpmInstallerFactoryOptions {
                clean_on_install: options.clean_on_install,
                cache_setting: NpmCacheSetting::from_cache_setting(&options.cache_setting),
                caching_strategy: options.npm_caching,
                dedup_lockfile_peer_variants: true,
                lifecycle_scripts_config: Default::default(),
                production: options.production,
                skip_types: options.skip_types,
                resolve_npm_resolution_snapshot: Box::new(|| Ok(None)),
            },
        ));

        Ok(Self {
            cwd,
            lockfile,
            http_client,
            resolver_factory,
            npm_installer_factory,
            memory_files,
            graph_loader: Mutex::new(graph_loader),
            install_graph_roots: options.install_graph_roots,
            allow_json_imports: options.allow_json_imports,
            enable_raw_imports: options.enable_raw_imports,
            frozen_lockfile: options.frozen_lockfile.unwrap_or(false),
            unsafely_ignore_certificate_errors: options.unsafely_ignore_certificate_errors,
        })
    }

    pub fn http_client(&self) -> &Arc<EmbedHttpClient> {
        &self.http_client
    }

    pub fn resolver_factory(&self) -> &Arc<ResolverFactory<EmbedSys>> {
        &self.resolver_factory
    }

    pub fn npm_installer_factory(
        &self,
    ) -> &Rc<NpmInstallerFactory<EmbedHttpClient, LogReporter, EmbedSys>> {
        &self.npm_installer_factory
    }

    pub fn memory_files(&self) -> &deno_resolver::loader::MemoryFilesRc {
        &self.memory_files
    }

    pub fn graph_loader(
        &self,
    ) -> &Mutex<DenoGraphLoader<NullBlobStore, EmbedSys, EmbedHttpClient>> {
        &self.graph_loader
    }

    pub fn install_graph_roots(&self) -> &[ModuleSpecifier] {
        &self.install_graph_roots
    }

    pub fn allow_json_imports(&self) -> AllowJsonImports {
        self.allow_json_imports
    }

    pub fn enable_raw_imports(&self) -> bool {
        self.enable_raw_imports
    }

    pub fn frozen_lockfile(&self) -> bool {
        self.frozen_lockfile
    }

    pub fn unsafely_ignore_certificate_errors(&self) -> Option<Vec<String>> {
        self.unsafely_ignore_certificate_errors.clone()
    }

    pub fn insert_memory_file(&self, url: Url, source: String) {
        memory::insert_memory_file(&self.memory_files, url, source);
    }
}

#[cfg(test)]
mod tests {
    use deno_cache_dir::file_fetcher::CacheSetting;
    use deno_resolver::loader::AllowJsonImports;

    use super::EmbedContextOptions;

    #[test]
    fn requires_embed_module_loader_is_false_for_defaults() {
        assert!(!EmbedContextOptions::default().requires_embed_module_loader());
    }

    #[test]
    fn requires_embed_module_loader_is_true_for_non_default_resolution_options() {
        let cases = [
            (
                EmbedContextOptions {
                    allow_json_imports: AllowJsonImports::Always,
                    ..Default::default()
                },
                "allow_json_imports",
            ),
            (
                EmbedContextOptions {
                    allow_remote: false,
                    ..Default::default()
                },
                "allow_remote",
            ),
            (
                EmbedContextOptions {
                    no_npm: true,
                    ..Default::default()
                },
                "no_npm",
            ),
            (
                EmbedContextOptions {
                    unsafely_ignore_certificate_errors: Some(vec!["localhost".to_string()]),
                    ..Default::default()
                },
                "unsafely_ignore_certificate_errors",
            ),
            (
                EmbedContextOptions {
                    cache_setting: CacheSetting::ReloadAll,
                    ..Default::default()
                },
                "cache_setting",
            ),
        ];

        for (options, label) in cases {
            assert!(
                options.requires_embed_module_loader(),
                "expected {label} to require embed module loader"
            );
        }
    }
}
