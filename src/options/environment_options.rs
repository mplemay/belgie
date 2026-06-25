use deno_cache_dir::file_fetcher::CacheSetting;
use deno_config::deno_json::{NodeModulesDirMode, NodeModulesLinkerMode};
use deno_npm_installer::graph::NpmCachingStrategy;
use deno_resolver::loader::AllowJsonImports;

#[derive(Clone, Debug)]
pub(crate) struct EnvironmentOptions {
    cache_setting: CacheSetting,
    allow_remote: bool,
    allow_json_imports: AllowJsonImports,
    node_modules_dir: Option<NodeModulesDirMode>,
    node_modules_linker: Option<NodeModulesLinkerMode>,
    npm_caching: NpmCachingStrategy,
    no_npm: bool,
    clean_on_install: bool,
    production: bool,
    skip_types: bool,
    unsafely_ignore_certificate_errors: Option<Vec<String>>,
}

impl Default for EnvironmentOptions {
    fn default() -> Self {
        Self {
            cache_setting: CacheSetting::Use,
            allow_remote: true,
            allow_json_imports: AllowJsonImports::WithAttribute,
            node_modules_dir: None,
            node_modules_linker: None,
            npm_caching: NpmCachingStrategy::Eager,
            no_npm: false,
            clean_on_install: true,
            production: false,
            skip_types: false,
            unsafely_ignore_certificate_errors: None,
        }
    }
}

impl EnvironmentOptions {
    #[allow(
        clippy::too_many_arguments,
        reason = "mirrors the normalized EnvironmentOptions binding fields"
    )]
    pub(crate) fn new(
        cache_setting: CacheSetting,
        allow_remote: bool,
        allow_json_imports: AllowJsonImports,
        node_modules_dir: Option<NodeModulesDirMode>,
        node_modules_linker: Option<NodeModulesLinkerMode>,
        npm_caching: NpmCachingStrategy,
        no_npm: bool,
        clean_on_install: bool,
        production: bool,
        skip_types: bool,
        unsafely_ignore_certificate_errors: Option<Vec<String>>,
    ) -> Self {
        Self {
            cache_setting,
            allow_remote,
            allow_json_imports,
            node_modules_dir,
            node_modules_linker,
            npm_caching,
            no_npm,
            clean_on_install,
            production,
            skip_types,
            unsafely_ignore_certificate_errors,
        }
    }

    pub(crate) fn cache_setting(&self) -> &CacheSetting {
        &self.cache_setting
    }

    pub(crate) fn allow_remote(&self) -> bool {
        self.allow_remote
    }

    pub(crate) fn allow_json_imports(&self) -> AllowJsonImports {
        self.allow_json_imports
    }

    pub(crate) fn node_modules_dir(&self) -> Option<NodeModulesDirMode> {
        self.node_modules_dir
    }

    pub(crate) fn node_modules_linker(&self) -> Option<NodeModulesLinkerMode> {
        self.node_modules_linker
    }

    pub(crate) fn npm_caching(&self) -> NpmCachingStrategy {
        self.npm_caching
    }

    pub(crate) fn no_npm(&self) -> bool {
        self.no_npm
    }

    pub(crate) fn clean_on_install(&self) -> bool {
        self.clean_on_install
    }

    pub(crate) fn production(&self) -> bool {
        self.production
    }

    pub(crate) fn skip_types(&self) -> bool {
        self.skip_types
    }

    pub(crate) fn unsafely_ignore_certificate_errors(&self) -> Option<Vec<String>> {
        self.unsafely_ignore_certificate_errors.clone()
    }
}

#[cfg(test)]
mod tests {
    use deno_cache_dir::file_fetcher::CacheSetting;
    use deno_resolver::loader::AllowJsonImports;

    use super::EnvironmentOptions;

    #[test]
    fn default_options_preserve_current_environment_behavior() {
        let options = EnvironmentOptions::default();

        assert!(matches!(options.cache_setting(), CacheSetting::Use));
        assert!(options.allow_remote());
        assert!(matches!(
            options.allow_json_imports(),
            AllowJsonImports::WithAttribute
        ));
        assert!(options.node_modules_dir().is_none());
        assert!(options.node_modules_linker().is_none());
        assert!(!options.no_npm());
        assert!(options.clean_on_install());
        assert!(!options.production());
        assert!(!options.skip_types());
        assert!(options.unsafely_ignore_certificate_errors().is_none());
    }
}
