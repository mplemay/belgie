use std::collections::BTreeMap;

use pyo3::{Bound, PyAny, PyResult, types::PyAnyMethods};

pub(crate) enum GroupsDefault {
    All,
    Default,
}

pub(crate) fn normalize_groups(
    groups: Option<&Bound<'_, PyAny>>,
    default: GroupsDefault,
) -> PyResult<Option<Vec<String>>> {
    match groups {
        None => Ok(match default {
            GroupsDefault::All => None,
            GroupsDefault::Default => Some(vec!["default".into()]),
        }),
        Some(value) if value.is_none() => Ok(match default {
            GroupsDefault::All => None,
            GroupsDefault::Default => Some(vec!["default".into()]),
        }),
        Some(value) => value.extract().map(Some),
    }
}

pub(crate) fn normalize_dependencies(
    dependencies: Option<&Bound<'_, PyAny>>,
) -> PyResult<BTreeMap<String, String>> {
    match dependencies {
        Some(value) if !value.is_none() => value.extract(),
        _ => Ok(BTreeMap::new()),
    }
}
