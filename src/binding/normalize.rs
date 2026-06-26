use pyo3::{PyResult, exceptions::PyValueError};

pub(crate) fn normalize_non_negative_u64(
    field_name: &str,
    value: Option<i64>,
) -> PyResult<Option<u64>> {
    match value {
        Some(value) if value < 0 => Err(PyValueError::new_err(format!(
            "{field_name} must be a non-negative integer"
        ))),
        Some(value) => Ok(Some(value as u64)),
        None => Ok(None),
    }
}
