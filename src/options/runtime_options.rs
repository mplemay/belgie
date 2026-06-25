use std::path::{Path, PathBuf};

use deno_runtime::WorkerLogLevel;
use deno_runtime::deno_permissions::{PermissionDescriptorParser, Permissions, PermissionsOptions};

use crate::embed::sys::EmbedSys;
use crate::environment::SharedEnvironment;

#[derive(Clone, Debug)]
pub(crate) struct RuntimeOptions {
    cwd: PathBuf,
    js_runtime: JsRuntimeOptions,
    worker: RuntimeWorkerOptions,
    environment: Option<RuntimeEnvironment>,
}

#[derive(Clone, Debug)]
pub(crate) enum RuntimeEnvironment {
    Isolated(SharedEnvironment),
}

#[derive(Clone, Debug, Default)]
pub(crate) struct JsRuntimeOptions {
    max_old_generation_size_mb: Option<u64>,
    max_young_generation_size_mb: Option<u64>,
    code_range_size_mb: Option<u64>,
}

#[derive(Clone, Debug, Default)]
pub(crate) struct RuntimeWorkerOptions {
    permissions: RuntimePermissionOptions,
    seed: Option<u64>,
    location: Option<url::Url>,
    log_level: Option<WorkerLogLevel>,
    enable_testing_features: bool,
    enable_raw_imports: bool,
    trace_ops: Option<Vec<String>>,
}

#[derive(Clone, Debug, Default)]
pub(crate) enum RuntimePermissionOptions {
    #[default]
    AllowAll,
    None {
        prompt: bool,
    },
    Configured(Box<PermissionsOptions>),
}

impl RuntimeOptions {
    #[cfg(test)]
    pub(crate) fn new(cwd: PathBuf) -> Self {
        Self::new_with_js_runtime_options(cwd, JsRuntimeOptions::default(), None)
    }

    #[cfg(test)]
    pub(crate) fn new_with_js_runtime_options(
        cwd: PathBuf,
        js_runtime: JsRuntimeOptions,
        environment: Option<RuntimeEnvironment>,
    ) -> Self {
        Self::new_with_options(
            cwd,
            js_runtime,
            RuntimeWorkerOptions::default(),
            environment,
        )
    }

    pub(crate) fn new_with_options(
        cwd: PathBuf,
        js_runtime: JsRuntimeOptions,
        worker: RuntimeWorkerOptions,
        environment: Option<RuntimeEnvironment>,
    ) -> Self {
        Self {
            cwd,
            js_runtime,
            worker,
            environment,
        }
    }

    pub(crate) fn cwd(&self) -> &Path {
        &self.cwd
    }

    pub(crate) fn js_runtime(&self) -> &JsRuntimeOptions {
        &self.js_runtime
    }

    pub(crate) fn worker(&self) -> &RuntimeWorkerOptions {
        &self.worker
    }

    pub(crate) fn environment(&self) -> Option<&RuntimeEnvironment> {
        self.environment.as_ref()
    }
}

impl RuntimeEnvironment {
    pub(crate) fn isolated(&self) -> Option<&SharedEnvironment> {
        match self {
            Self::Isolated(environment) => Some(environment),
        }
    }
}

impl RuntimeWorkerOptions {
    pub(crate) fn new(
        permissions: RuntimePermissionOptions,
        seed: Option<u64>,
        location: Option<url::Url>,
        log_level: Option<WorkerLogLevel>,
        enable_testing_features: bool,
        enable_raw_imports: bool,
        trace_ops: Option<Vec<String>>,
    ) -> Self {
        Self {
            permissions,
            seed,
            location,
            log_level,
            enable_testing_features,
            enable_raw_imports,
            trace_ops,
        }
    }

    pub(crate) fn requires_package_worker(&self) -> bool {
        !matches!(self.permissions, RuntimePermissionOptions::AllowAll)
            || self.seed.is_some()
            || self.location.is_some()
            || self.log_level.is_some()
            || self.enable_testing_features
            || self.enable_raw_imports
            || self.trace_ops.is_some()
    }

    pub(crate) fn permissions(&self) -> &RuntimePermissionOptions {
        &self.permissions
    }

    pub(crate) fn seed(&self) -> Option<u64> {
        self.seed
    }

    pub(crate) fn location(&self) -> Option<url::Url> {
        self.location.clone()
    }

    pub(crate) fn log_level(&self) -> Option<WorkerLogLevel> {
        self.log_level
    }

    pub(crate) fn enable_testing_features(&self) -> bool {
        self.enable_testing_features
    }

    pub(crate) fn enable_raw_imports(&self) -> bool {
        self.enable_raw_imports
    }

    pub(crate) fn trace_ops(&self) -> Option<Vec<String>> {
        self.trace_ops.clone()
    }
}

impl RuntimePermissionOptions {
    pub(crate) fn none(prompt: bool) -> Self {
        Self::None { prompt }
    }

    pub(crate) fn configured(options: PermissionsOptions) -> Self {
        Self::Configured(Box::new(options))
    }

    pub(crate) fn to_permissions(&self) -> Result<Permissions, String> {
        match self {
            Self::AllowAll => Ok(Permissions::allow_all()),
            Self::None { prompt } => {
                if *prompt {
                    Ok(Permissions::none_with_prompt())
                } else {
                    Ok(Permissions::none_without_prompt())
                }
            }
            Self::Configured(options) => {
                let parser = deno_runtime::permissions::RuntimePermissionDescriptorParser::new(
                    EmbedSys::default(),
                );
                Permissions::from_options(&parser as &dyn PermissionDescriptorParser, options)
                    .map_err(|error| error.to_string())
            }
        }
    }
}

impl JsRuntimeOptions {
    pub(crate) fn new(
        max_old_generation_size_mb: Option<u64>,
        max_young_generation_size_mb: Option<u64>,
        code_range_size_mb: Option<u64>,
    ) -> Self {
        Self {
            max_old_generation_size_mb,
            max_young_generation_size_mb,
            code_range_size_mb,
        }
    }

    pub(crate) fn to_create_params(&self) -> Result<Option<deno_core::v8::CreateParams>, String> {
        if self.max_old_generation_size_mb.is_none()
            && self.max_young_generation_size_mb.is_none()
            && self.code_range_size_mb.is_none()
        {
            return Ok(None);
        }

        let mut params = deno_core::v8::CreateParams::default();
        if let Some(value) = self.max_old_generation_size_mb {
            params = params.set_max_old_generation_size_in_bytes(mb_to_bytes(
                value,
                "max_old_generation_size_mb",
            )?);
        }
        if let Some(value) = self.max_young_generation_size_mb {
            params = params.set_max_young_generation_size_in_bytes(mb_to_bytes(
                value,
                "max_young_generation_size_mb",
            )?);
        }
        if let Some(value) = self.code_range_size_mb {
            params = params.set_code_range_size_in_bytes(mb_to_bytes(value, "code_range_size_mb")?);
        }
        Ok(Some(params))
    }

    pub(crate) fn max_old_generation_size_mb(&self) -> Option<u64> {
        self.max_old_generation_size_mb
    }

    pub(crate) fn max_young_generation_size_mb(&self) -> Option<u64> {
        self.max_young_generation_size_mb
    }

    pub(crate) fn code_range_size_mb(&self) -> Option<u64> {
        self.code_range_size_mb
    }
}

fn mb_to_bytes(value: u64, field_name: &str) -> Result<usize, String> {
    if value == 0 {
        return Err(format!("{field_name} must be a positive integer"));
    }
    let bytes = value
        .checked_mul(1024)
        .and_then(|value| value.checked_mul(1024))
        .ok_or_else(|| format!("{field_name} is too large"))?;
    usize::try_from(bytes).map_err(|_| format!("{field_name} is too large"))
}

#[cfg(test)]
mod tests {
    use deno_runtime::deno_permissions::PermissionsOptions;

    use super::{JsRuntimeOptions, RuntimeOptions, RuntimePermissionOptions, RuntimeWorkerOptions};
    use std::path::PathBuf;

    #[test]
    fn stores_the_runtime_working_directory() {
        let cwd = PathBuf::from("/tmp/belgie/project");
        let options = RuntimeOptions::new(cwd.clone());

        assert_eq!(options.cwd(), cwd.as_path());
    }

    #[test]
    fn default_js_runtime_options_do_not_create_v8_params() {
        let options = JsRuntimeOptions::default();

        assert!(options.to_create_params().unwrap().is_none());
    }

    #[test]
    fn js_runtime_options_create_v8_params() {
        let options = JsRuntimeOptions::new(Some(64), Some(16), Some(32));
        let params = options.to_create_params().unwrap().unwrap();

        assert_eq!(params.max_old_generation_size_in_bytes(), 64 * 1024 * 1024);
        assert_eq!(
            params.max_young_generation_size_in_bytes(),
            16 * 1024 * 1024
        );
        assert_eq!(params.code_range_size_in_bytes(), 32 * 1024 * 1024);
    }

    #[test]
    fn js_runtime_options_reject_zero_values() {
        let options = JsRuntimeOptions::new(Some(0), None, None);

        assert!(options.to_create_params().unwrap_err().contains("positive"));
    }

    #[test]
    fn js_runtime_options_reject_overflowing_values() {
        let options = JsRuntimeOptions::new(Some(u64::MAX), None, None);

        assert!(
            options
                .to_create_params()
                .unwrap_err()
                .contains("too large")
        );
    }

    #[test]
    fn default_worker_options_do_not_require_package_worker() {
        assert!(!RuntimeWorkerOptions::default().requires_package_worker());
    }

    #[test]
    fn restrictive_permissions_require_package_worker() {
        let options = RuntimeWorkerOptions::new(
            RuntimePermissionOptions::none(false),
            None,
            None,
            None,
            false,
            false,
            None,
        );

        assert!(options.requires_package_worker());
    }

    #[test]
    fn configured_empty_permission_lists_keep_deno_global_allow_semantics() {
        let permissions = RuntimePermissionOptions::configured(PermissionsOptions {
            allow_read: Some(Vec::new()),
            ..Default::default()
        })
        .to_permissions()
        .unwrap();

        assert!(permissions.read.is_allow_all());
    }
}
