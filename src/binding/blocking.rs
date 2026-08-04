use deno_core::error::AnyError;
use pyo3::PyResult;

use crate::exceptions::BelgieRuntimeError;
use crate::utils::minimum_dependency_age::with_minimum_dependency_age_hint;

pub(crate) async fn run_on_blocking_thread<T, F>(
    operation: F,
    join_error_context: &str,
) -> PyResult<T>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, AnyError> + Send + 'static,
{
    tokio::task::spawn_blocking(operation)
        .await
        .map_err(|error| BelgieRuntimeError::new_err(format!("{join_error_context}: {error}")))?
        .map_err(any_error_to_py)
}

pub(crate) fn any_error_to_py(error: AnyError) -> pyo3::PyErr {
    BelgieRuntimeError::new_err(with_minimum_dependency_age_hint(error.to_string()))
}
