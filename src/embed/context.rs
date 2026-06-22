use std::collections::HashMap;
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::Arc;

use deno_cache_dir::file_fetcher::CacheSetting;
use deno_cache_dir::file_fetcher::NullBlobStore;
use deno_cache_dir::file_fetcher::SendError;
use deno_cache_dir::file_fetcher::SendResponse;
use deno_config::deno_json::NodeModulesDirMode;
use deno_core::error::AnyError;
use deno_core::url::Url;
use deno_error::JsErrorBox;
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
use deno_resolver::factory::WorkspaceFactory;
use deno_resolver::factory::WorkspaceFactoryOptions;
use deno_resolver::file_fetcher::DenoGraphLoader;
use deno_resolver::file_fetcher::DenoGraphLoaderOptions;
use deno_resolver::file_fetcher::PermissionedFileFetcher;
use deno_resolver::file_fetcher::PermissionedFileFetcherOptions;
use deno_resolver::loader::AllowJsonImports;
use deno_resolver::loader::MemoryFiles;
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
    fn new(root_cert_store: RootCertStore) -> Result<Self, AnyError> {
        let client = create_http_client(
            DENO_VERSION_INFO.user_agent,
            CreateHttpClientOptions {
                root_cert_store: Some(root_cert_store),
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
    pub config_file: PathBuf,
    pub lockfile: PathBuf,
    http_client: Arc<EmbedHttpClient>,
    resolver_factory: Arc<ResolverFactory<EmbedSys>>,
    npm_installer_factory: Rc<NpmInstallerFactory<EmbedHttpClient, LogReporter, EmbedSys>>,
    memory_files: deno_resolver::loader::MemoryFilesRc,
    graph_loader: Mutex<DenoGraphLoader<NullBlobStore, EmbedSys, EmbedHttpClient>>,
}

#[derive(Clone, Debug, Default)]
pub(crate) struct EmbedContextOptions {
    pub cache_root: Option<PathBuf>,
    pub frozen_lockfile: Option<bool>,
    pub is_package_manager_subcommand: bool,
    pub lockfile_skip_write: bool,
    pub node_modules_dir_mode: Option<NodeModulesDirMode>,
    pub node_modules_root: Option<PathBuf>,
}

impl EmbedContextOptions {
    pub(crate) fn for_package_manager(mut self) -> Self {
        self.is_package_manager_subcommand = true;
        self
    }
}

impl std::fmt::Debug for EmbedContext {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EmbedContext")
            .field("cwd", &self.cwd)
            .field("config_file", &self.config_file)
            .field("lockfile", &self.lockfile)
            .finish_non_exhaustive()
    }
}

impl EmbedContext {
    #[cfg(test)]
    pub fn new(cwd: PathBuf, config_file: PathBuf, lockfile: PathBuf) -> Result<Self, AnyError> {
        Self::new_with_options(cwd, config_file, lockfile, EmbedContextOptions::default())
    }

    pub fn new_with_options(
        cwd: PathBuf,
        config_file: PathBuf,
        lockfile: PathBuf,
        options: EmbedContextOptions,
    ) -> Result<Self, AnyError> {
        ensure_initialized();
        let sys = EmbedSys::default();
        let config_file = config_file.canonicalize().unwrap_or(config_file);
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
                config_discovery: ConfigDiscoveryOption::Path(config_file.clone()),
                lock_arg: Some(lockfile.clone()),
                is_package_manager_subcommand: options.is_package_manager_subcommand,
                frozen_lockfile: options.frozen_lockfile,
                lockfile_skip_write: options.lockfile_skip_write,
                maybe_custom_deno_dir_root: options.cache_root,
                node_modules_dir: Some(node_modules_dir),
                root_node_modules_dir_override: options.node_modules_root,
                ..Default::default()
            },
        ));

        let resolver_factory = Arc::new(ResolverFactory::new(
            workspace_factory,
            ResolverFactoryOptions {
                allow_json_imports: AllowJsonImports::WithAttribute,
                ..Default::default()
            },
        ));

        let root_cert_store = get_root_cert_store(&sys, None, None, None)?;
        let http_client = EmbedHttpClient::new(root_cert_store)?;
        let http_client_arc = Arc::new(http_client.clone());
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
            http_client.clone(),
            memory_files.clone(),
            sys.clone(),
            PermissionedFileFetcherOptions {
                allow_remote: true,
                cache_setting: CacheSetting::Use,
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
                include_npm_sources: true,
            },
        );

        let npm_installer_factory = Rc::new(NpmInstallerFactory::new(
            resolver_factory.clone(),
            http_client_arc.clone(),
            Arc::new(NullLifecycleScriptsExecutor),
            LogReporter,
            None,
            NpmInstallerFactoryOptions {
                clean_on_install: true,
                cache_setting: NpmCacheSetting::Use,
                caching_strategy: NpmCachingStrategy::Eager,
                dedup_lockfile_peer_variants: true,
                lifecycle_scripts_config: Default::default(),
                production: false,
                skip_types: false,
                resolve_npm_resolution_snapshot: Box::new(|| Ok(None)),
            },
        ));

        Ok(Self {
            cwd,
            config_file,
            lockfile,
            http_client: http_client_arc,
            resolver_factory,
            npm_installer_factory,
            memory_files,
            graph_loader: Mutex::new(graph_loader),
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

    pub fn insert_memory_file(&self, url: Url, source: String) {
        memory::insert_memory_file(&self.memory_files, url, source);
    }
}
