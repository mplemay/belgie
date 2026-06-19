use std::collections::BTreeMap;

use pyo3::{Bound, PyAny, PyResult, types::PyAnyMethods};

pub(crate) fn normalize_dependencies(
    dependencies: Option<&Bound<'_, PyAny>>,
) -> PyResult<BTreeMap<String, String>> {
    match dependencies {
        Some(value) if !value.is_none() => value.extract(),
        _ => Ok(BTreeMap::new()),
    }
}
