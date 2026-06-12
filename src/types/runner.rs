use deno_core::{
    serde_json::{Map, Value},
    v8,
};
use pyo3::{
    Bound, Py, PyAny, PyResult,
    types::{PyAnyMethods, PyDict, PyDictMethods, PyTuple, PyTupleMethods},
};

use crate::types::{error::BindingError, value::PyJsValue};

pub(crate) type SyncRunnerResult = PyResult<Py<PyAny>>;
pub(crate) type AsyncRunnerResult = PyResult<Py<PyAny>>;

#[derive(Clone, Debug)]
pub(crate) struct RunnerArguments {
    positional: Vec<PyJsValue>,
    keyword: Map<String, Value>,
}

impl RunnerArguments {
    pub(crate) fn from_py(
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Self> {
        let positional = args
            .iter()
            .map(|value| PyJsValue::from_py(&value))
            .collect::<PyResult<Vec<_>>>()?;
        let mut keyword = Map::new();
        if let Some(kwargs) = kwargs {
            for (key, value) in kwargs.iter() {
                keyword.insert(
                    key.extract::<String>()?,
                    PyJsValue::from_py(&value)?.as_json().clone(),
                );
            }
        }
        Ok(Self {
            positional,
            keyword,
        })
    }

    #[cfg(test)]
    pub(crate) fn is_empty(&self) -> bool {
        self.positional.is_empty() && self.keyword.is_empty()
    }

    pub(crate) fn values_for_call(&self) -> Vec<PyJsValue> {
        let mut values = self.positional.clone();
        if !self.keyword.is_empty() {
            values.push(PyJsValue::from_json(Value::Object(self.keyword.clone())));
        }
        values
    }

    pub(crate) fn to_v8_globals(
        &self,
        scope: &mut v8::PinScope<'_, '_>,
    ) -> Result<Vec<v8::Global<v8::Value>>, BindingError> {
        self.values_for_call()
            .iter()
            .map(|value| {
                let local = value.to_v8(scope)?;
                Ok(v8::Global::new(scope, local))
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::RunnerArguments;
    use pyo3::{
        Python,
        types::{PyDict, PyDictMethods, PyTuple},
    };

    fn with_python<R>(test: impl FnOnce(Python<'_>) -> R) -> R {
        Python::initialize();
        Python::attach(test)
    }

    #[test]
    fn empty_python_arguments_are_empty() {
        with_python(|py| {
            let args = PyTuple::empty(py);

            let arguments = RunnerArguments::from_py(&args, None).expect("args should convert");

            assert!(arguments.is_empty());
        });
    }

    #[test]
    fn positional_and_keyword_arguments_make_runner_arguments_non_empty() {
        with_python(|py| {
            let args = PyTuple::new(py, [41i32]).expect("tuple should build");
            let kwargs = PyDict::new(py);
            kwargs
                .set_item("flag", true)
                .expect("keyword should be inserted");

            let arguments =
                RunnerArguments::from_py(&args, Some(&kwargs)).expect("args should convert");

            assert!(!arguments.is_empty());
        });
    }

    #[test]
    fn preserves_python_argument_values_for_future_js_invocation() {
        with_python(|py| {
            let args = PyTuple::new(py, ["deno"]).expect("tuple should build");
            let kwargs = PyDict::new(py);
            kwargs
                .set_item("flag", true)
                .expect("keyword should be inserted");

            let arguments =
                RunnerArguments::from_py(&args, Some(&kwargs)).expect("args should convert");
            let debug = format!("{arguments:?}");

            assert!(
                debug.contains("deno") && debug.contains("flag"),
                "RunnerArguments should preserve values and keyword names for JS invocation, got {debug}"
            );
        });
    }
}
