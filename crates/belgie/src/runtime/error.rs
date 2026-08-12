use deno_core::error::AnyError;
use deno_graph::ModuleGraphError;

use crate::types::error::BindingError;
use crate::utils::minimum_dependency_age::with_minimum_dependency_age_hint;

const MODULE_NOT_FOUND: &str = "Module not found";

pub fn map_package_environment_error(error: impl std::fmt::Display) -> BindingError {
    let message = with_minimum_dependency_age_hint(error.to_string());
    if message.starts_with(MODULE_NOT_FOUND) {
        return BindingError::module_load(message);
    }
    BindingError::runtime(format!(
        "Environment dependencies are missing or out of date: {message}"
    ))
}

pub fn map_package_runtime_preparation_error(error: AnyError) -> BindingError {
    if error.downcast_ref::<ModuleGraphError>().is_some() {
        BindingError::module_load(with_minimum_dependency_age_hint(error.to_string()))
    } else {
        map_package_environment_error(error)
    }
}
