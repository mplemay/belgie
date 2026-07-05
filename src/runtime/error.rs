use crate::types::error::BindingError;

pub(crate) fn map_package_environment_error(error: impl std::fmt::Display) -> BindingError {
    let message = error.to_string();
    if message.contains("Module not found") {
        return BindingError::module_load(message);
    }
    BindingError::runtime(format!(
        "Environment dependencies are missing or out of date: {message}"
    ))
}
