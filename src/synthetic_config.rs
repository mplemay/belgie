use std::path::Path;

use deno_core::anyhow::{Context, anyhow};
use deno_core::error::AnyError;
use deno_core::serde_json;

pub(crate) fn is_registry_import_specifier(specifier: &str) -> bool {
    specifier.starts_with("npm:") || specifier.starts_with("jsr:")
}

pub(crate) fn is_node_modules_import_specifier(specifier: &str) -> bool {
    specifier.starts_with("./node_modules/")
}

fn missing_imports_table_error() -> AnyError {
    anyhow!("Synthetic belgie Deno config is missing an imports table")
}

pub(crate) fn read_synthetic_config_document(
    config_file: &Path,
) -> Result<serde_json::Value, AnyError> {
    let text = std::fs::read_to_string(config_file)
        .with_context(|| format!("Reading {}", config_file.display()))?;
    serde_json::from_str(&text).with_context(|| format!("Parsing {}", config_file.display()))
}

pub(crate) fn read_synthetic_config_imports(
    config_file: &Path,
) -> Result<serde_json::Map<String, serde_json::Value>, AnyError> {
    read_synthetic_config_document(config_file)?
        .get("imports")
        .and_then(|value| value.as_object())
        .cloned()
        .ok_or_else(missing_imports_table_error)
}

pub(crate) fn write_synthetic_config_document(
    path: &Path,
    config: &serde_json::Value,
) -> Result<(), AnyError> {
    let text = serde_json::to_string_pretty(config)?;
    std::fs::write(path, format!("{text}\n")).with_context(|| format!("Writing {}", path.display()))
}

pub(crate) fn synthetic_config_imports_mut(
    config: &mut serde_json::Value,
) -> Result<&mut serde_json::Map<String, serde_json::Value>, AnyError> {
    config
        .get_mut("imports")
        .and_then(|value| value.as_object_mut())
        .ok_or_else(missing_imports_table_error)
}

pub(crate) fn synthetic_config_imports(
    config: &serde_json::Value,
) -> Result<&serde_json::Map<String, serde_json::Value>, AnyError> {
    config
        .get("imports")
        .and_then(|value| value.as_object())
        .ok_or_else(missing_imports_table_error)
}
