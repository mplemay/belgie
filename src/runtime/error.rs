use crate::types::error::BindingError;

pub(crate) fn map_package_environment_error(error: impl std::fmt::Display) -> BindingError {
    BindingError::runtime(format!(
        "Environment dependencies are missing or out of date: {error}"
    ))
}
