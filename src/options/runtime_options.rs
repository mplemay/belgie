use std::path::{Path, PathBuf};

use crate::environment::SharedEnvironment;

#[derive(Clone, Debug)]
pub(crate) struct RuntimeOptions {
    cwd: PathBuf,
    js_runtime: JsRuntimeOptions,
    environment: Option<RuntimeEnvironment>,
}

#[derive(Clone, Debug)]
pub(crate) enum RuntimeEnvironment {
    External(SharedEnvironment),
    Owned(SharedEnvironment),
}

#[derive(Clone, Debug, Default)]
pub(crate) struct JsRuntimeOptions {
    max_old_generation_size_mb: Option<u64>,
    max_young_generation_size_mb: Option<u64>,
    code_range_size_mb: Option<u64>,
}

impl RuntimeOptions {
    #[cfg(test)]
    pub(crate) fn new(cwd: PathBuf) -> Self {
        Self::new_with_js_runtime_options(cwd, JsRuntimeOptions::default(), None)
    }

    pub(crate) fn new_with_js_runtime_options(
        cwd: PathBuf,
        js_runtime: JsRuntimeOptions,
        environment: Option<RuntimeEnvironment>,
    ) -> Self {
        Self {
            cwd,
            js_runtime,
            environment,
        }
    }

    pub(crate) fn cwd(&self) -> &Path {
        &self.cwd
    }

    pub(crate) fn js_runtime(&self) -> &JsRuntimeOptions {
        &self.js_runtime
    }

    pub(crate) fn environment(&self) -> Option<&RuntimeEnvironment> {
        self.environment.as_ref()
    }
}

impl RuntimeEnvironment {
    pub(crate) fn environment(&self) -> &SharedEnvironment {
        match self {
            Self::External(environment) | Self::Owned(environment) => environment,
        }
    }

    pub(crate) fn is_owned(&self) -> bool {
        matches!(self, Self::Owned(_))
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
    use super::{JsRuntimeOptions, RuntimeOptions};
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
}
