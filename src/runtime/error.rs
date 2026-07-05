use crate::types::error::BindingError;

const MODULE_NOT_FOUND: &str = "Module not found";

pub(crate) fn map_package_environment_error(error: impl std::fmt::Display) -> BindingError {
    let message = error.to_string();
    if message.starts_with(MODULE_NOT_FOUND) {
        return BindingError::module_load(message);
    }
    BindingError::runtime(format!(
        "Environment dependencies are missing or out of date: {message}"
    ))
}
