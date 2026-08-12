use std::collections::HashSet;

use belgie::types::runner::RunnerArguments;
use belgie::types::value::JsValue;
use pyo3::{
    Bound, Py, PyAny, PyResult, Python,
    conversion::IntoPyObjectExt,
    exceptions::{PyTypeError, PyValueError},
    types::{
        PyAnyMethods, PyDict, PyDictMethods, PyFloat, PyInt, PyList, PyListMethods, PyString,
        PyStringMethods, PyTuple, PyTupleMethods, PyTypeMethods,
    },
};
use serde_json::{Map, Number, Value};

const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

pub fn js_value_from_py(value: &Bound<'_, PyAny>) -> PyResult<JsValue> {
    let mut seen = HashSet::new();
    Ok(JsValue::from_json(value_from_py(value, "$", &mut seen)?))
}

pub fn js_value_to_py(value: &JsValue, py: Python<'_>) -> PyResult<Py<PyAny>> {
    json_to_py(py, value.as_json())
}

pub fn runner_arguments_from_py(
    args: &Bound<'_, PyTuple>,
    kwargs: Option<&Bound<'_, PyDict>>,
) -> PyResult<RunnerArguments> {
    let positional = args
        .iter()
        .map(|value| js_value_from_py(&value))
        .collect::<PyResult<Vec<_>>>()?;
    let mut keyword = Map::new();
    if let Some(kwargs) = kwargs {
        for (key, value) in kwargs.iter() {
            keyword.insert(
                key.extract::<String>()?,
                js_value_from_py(&value)?.as_json().clone(),
            );
        }
    }
    Ok(RunnerArguments::new(positional, keyword))
}

fn value_from_py(
    value: &Bound<'_, PyAny>,
    path: &str,
    seen: &mut HashSet<usize>,
) -> PyResult<Value> {
    if value.is_none() {
        return Ok(Value::Null);
    }
    if let Ok(value) = value.extract::<bool>() {
        return Ok(Value::Bool(value));
    }
    if value.cast::<PyInt>().is_ok() {
        if let Ok(value) = value.extract::<i64>()
            && (-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(&value)
        {
            return Ok(Value::Number(Number::from(value)));
        }
        if let Ok(value) = value.extract::<u64>()
            && value <= MAX_SAFE_INTEGER as u64
        {
            return Ok(Value::Number(Number::from(value)));
        }
        return Err(PyValueError::new_err(format!(
            "Python int at {path} must be within the JavaScript safe integer range",
        )));
    }
    if value.cast::<PyFloat>().is_ok() {
        let number = value.extract::<f64>()?;
        if !number.is_finite() {
            return Err(PyValueError::new_err(format!(
                "Python float at {path} must be finite to pass as JSON",
            )));
        }
        return Number::from_f64(number).map(Value::Number).ok_or_else(|| {
            PyValueError::new_err(format!(
                "Could not convert Python float at {path} to a JSON number",
            ))
        });
    }
    if value.cast::<PyString>().is_ok() {
        return Ok(Value::String(value.extract::<String>()?));
    }
    if let Ok(dict) = value.cast::<PyDict>() {
        let id = value.as_ptr() as usize;
        if !seen.insert(id) {
            return Err(PyValueError::new_err(format!(
                "Cannot pass Python data structure cycle as JSON at {path}",
            )));
        }
        let mut object = Map::new();
        for (key, value) in dict.iter() {
            let key = key.extract::<String>().map_err(|_| {
                PyTypeError::new_err(format!("JSON object keys must be strings at {path}",))
            })?;
            let item_path = object_path(path, &key);
            object.insert(key, value_from_py(&value, &item_path, seen)?);
        }
        seen.remove(&id);
        return Ok(Value::Object(object));
    }
    if let Ok(list) = value.cast::<PyList>() {
        let id = value.as_ptr() as usize;
        if !seen.insert(id) {
            return Err(PyValueError::new_err(format!(
                "Cannot pass Python data structure cycle as JSON at {path}",
            )));
        }
        let mut array = Vec::with_capacity(list.len());
        for (index, value) in list.iter().enumerate() {
            array.push(value_from_py(&value, &array_path(path, index), seen)?);
        }
        seen.remove(&id);
        return Ok(Value::Array(array));
    }
    if let Ok(tuple) = value.cast::<PyTuple>() {
        let id = value.as_ptr() as usize;
        if !seen.insert(id) {
            return Err(PyValueError::new_err(format!(
                "Cannot pass Python data structure cycle as JSON at {path}",
            )));
        }
        let mut array = Vec::with_capacity(tuple.len());
        for (index, value) in tuple.iter().enumerate() {
            array.push(value_from_py(&value, &array_path(path, index), seen)?);
        }
        seen.remove(&id);
        return Ok(Value::Array(array));
    }

    let type_name = value.get_type().name()?.to_string_lossy().into_owned();
    Err(PyTypeError::new_err(format!(
        "Only JSON-serializable values can be passed to JavaScript at {path}; got {type_name}",
    )))
}

fn json_to_py(py: Python<'_>, value: &Value) -> PyResult<Py<PyAny>> {
    match value {
        Value::Null => Ok(py.None()),
        Value::Bool(value) => (*value).into_py_any(py),
        Value::Number(value) => number_to_py(py, value),
        Value::String(value) => value.clone().into_py_any(py),
        Value::Array(values) => {
            let values = values
                .iter()
                .map(|value| json_to_py(py, value))
                .collect::<PyResult<Vec<_>>>()?;
            Ok(PyList::new(py, values)?.into_any().unbind())
        }
        Value::Object(values) => {
            let dict = PyDict::new(py);
            for (key, value) in values {
                dict.set_item(key, json_to_py(py, value)?)?;
            }
            Ok(dict.into_any().unbind())
        }
    }
}

fn number_to_py(py: Python<'_>, number: &Number) -> PyResult<Py<PyAny>> {
    if let Some(value) = number.as_i64() {
        return value.into_py_any(py);
    }
    if let Some(value) = number.as_u64() {
        return value.into_py_any(py);
    }
    let value = number
        .as_f64()
        .ok_or_else(|| PyValueError::new_err("Could not convert JSON number to Python"))?;
    if value.fract() == 0.0 && (-MAX_SAFE_INTEGER as f64..=MAX_SAFE_INTEGER as f64).contains(&value)
    {
        return (value as i64).into_py_any(py);
    }
    value.into_py_any(py)
}

fn array_path(path: &str, index: usize) -> String {
    format!("{path}[{index}]")
}

fn object_path(path: &str, key: &str) -> String {
    if key
        .chars()
        .next()
        .is_some_and(|char| char == '_' || char.is_ascii_alphabetic())
        && key
            .chars()
            .all(|char| char == '_' || char.is_ascii_alphanumeric())
    {
        format!("{path}.{key}")
    } else {
        format!("{path}[{key:?}]")
    }
}

#[cfg(test)]
mod tests {
    use super::{MAX_SAFE_INTEGER, js_value_from_py, js_value_to_py, runner_arguments_from_py};
    use belgie::types::value::JsValue;
    use pyo3::types::{PyAnyMethods, PyDict, PyDictMethods, PyList, PyListMethods, PyTuple};
    use serde_json::{Number, Value};

    fn with_python<R>(test: impl FnOnce(pyo3::Python<'_>) -> R) -> R {
        pyo3::Python::initialize();
        pyo3::Python::attach(test)
    }

    #[test]
    fn defines_python_to_javascript_conversion_contract() {
        with_python(|py| {
            let dict = PyDict::new(py);
            dict.set_item("name", "deno").expect("name should insert");
            dict.set_item("items", vec![1, 2, 3])
                .expect("items should insert");

            let value = js_value_from_py(dict.as_any()).expect("dict should convert");

            assert!(matches!(value.as_json(), Value::Object(_)));
        });
    }

    #[test]
    fn preserves_python_object_key_order() {
        with_python(|py| {
            let dict = PyDict::new(py);
            dict.set_item("z", 1).expect("z should insert");
            dict.set_item("a", 2).expect("a should insert");

            let value = js_value_from_py(dict.as_any()).expect("dict should convert");
            let Value::Object(object) = value.as_json() else {
                panic!("dict should convert to JSON object");
            };

            assert_eq!(object.keys().collect::<Vec<_>>(), ["z", "a"]);
        });
    }

    #[test]
    fn rejects_non_string_python_object_keys_with_json_path() {
        with_python(|py| {
            let dict = PyDict::new(py);
            dict.set_item(1, "value").expect("item should insert");

            let error = js_value_from_py(dict.as_any())
                .expect_err("non-string keys should fail")
                .to_string();

            assert!(error.contains("JSON object keys must be strings"));
            assert!(error.contains("$"));
        });
    }

    #[test]
    fn rejects_non_finite_python_numbers_with_json_path() {
        with_python(|py| {
            let dict = PyDict::new(py);
            dict.set_item("value", f64::NAN)
                .expect("item should insert");

            let error = js_value_from_py(dict.as_any())
                .expect_err("NaN should fail")
                .to_string();

            assert!(error.contains("$.value"));
            assert!(error.contains("finite"));
        });
    }

    #[test]
    fn rejects_python_ints_outside_javascript_safe_integer_range() {
        with_python(|py| {
            let too_large = MAX_SAFE_INTEGER + 1;

            let error = js_value_from_py(
                PyTuple::new(py, [too_large])
                    .expect("tuple should build")
                    .get_item(0)
                    .expect("item should exist")
                    .as_any(),
            )
            .expect_err("unsafe integer should fail")
            .to_string();

            assert!(error.contains("safe integer"));
        });
    }

    #[test]
    fn detects_cycles_before_recursive_descent() {
        with_python(|py| {
            let list = PyList::empty(py);
            list.append(&list).expect("cycle should append");

            let error = js_value_from_py(list.as_any())
                .expect_err("cycles should fail")
                .to_string();

            assert!(error.contains("cycle"));
            assert!(error.contains("$[0]"));
        });
    }

    #[test]
    fn defines_javascript_to_python_conversion_contract() {
        with_python(|py| {
            let value = JsValue::from_json(Value::Array(vec![
                Value::Null,
                Value::Bool(true),
                Value::Number(Number::from(42)),
                Value::String("deno".to_string()),
            ]));

            let py_value = js_value_to_py(&value, py).expect("value should convert to Python");

            assert!(py_value.bind(py).is_instance_of::<pyo3::types::PyList>());
        });
    }

    #[test]
    fn converts_json_integer_numbers_to_python_ints() {
        with_python(|py| {
            let value = JsValue::from_json(Value::Number(Number::from(42)));

            let py_value = js_value_to_py(&value, py).expect("value should convert to Python");

            assert!(py_value.bind(py).extract::<i64>().is_ok());
        });
    }

    #[test]
    fn empty_python_arguments_are_empty() {
        with_python(|py| {
            let args = PyTuple::empty(py);

            let arguments = runner_arguments_from_py(&args, None).expect("args should convert");

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
                runner_arguments_from_py(&args, Some(&kwargs)).expect("args should convert");

            assert!(!arguments.is_empty());
        });
    }
}
