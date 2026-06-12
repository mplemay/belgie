use std::collections::HashSet;

use deno_core::{
    serde_json::{Map, Number, Value},
    serde_v8, v8,
};
use pyo3::{
    Bound, Py, PyAny, PyResult, Python,
    conversion::IntoPyObjectExt,
    exceptions::{PyTypeError, PyValueError},
    types::{
        PyAnyMethods, PyDict, PyDictMethods, PyFloat, PyInt, PyList, PyListMethods, PyString,
        PyStringMethods, PyTuple, PyTupleMethods, PyTypeMethods,
    },
};

use crate::types::error::BindingError;

const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, PartialEq)]
pub struct PyJsValue {
    inner: Value,
}

impl PyJsValue {
    pub(crate) fn from_json(value: Value) -> Self {
        Self { inner: value }
    }

    pub(crate) fn as_json(&self) -> &Value {
        &self.inner
    }

    pub(crate) fn from_py(value: &Bound<'_, PyAny>) -> PyResult<Self> {
        let mut seen = HashSet::new();
        Ok(Self::from_json(Self::value_from_py(value, "$", &mut seen)?))
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
                object.insert(key, Self::value_from_py(&value, &item_path, seen)?);
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
                array.push(Self::value_from_py(&value, &array_path(path, index), seen)?);
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
                array.push(Self::value_from_py(&value, &array_path(path, index), seen)?);
            }
            seen.remove(&id);
            return Ok(Value::Array(array));
        }

        let type_name = value.get_type().name()?.to_string_lossy().into_owned();
        Err(PyTypeError::new_err(format!(
            "Only JSON-serializable values can be passed to JavaScript at {path}; got {type_name}",
        )))
    }

    pub(crate) fn to_py(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        json_to_py(py, &self.inner)
    }

    pub(crate) fn to_v8<'s, 'i>(
        &self,
        scope: &mut v8::PinScope<'s, 'i>,
    ) -> Result<v8::Local<'s, v8::Value>, BindingError> {
        serde_v8::to_v8(scope, &self.inner).map_err(|error| {
            BindingError::value_conversion(format!("Could not convert JSON value to V8: {error}",))
        })
    }

    pub(crate) fn from_v8<'s, 'i>(
        scope: &mut v8::PinScope<'s, 'i>,
        value: v8::Local<'s, v8::Value>,
    ) -> Result<Self, BindingError> {
        Ok(Self::from_json(value_from_v8(scope, value, "$")?))
    }
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

fn value_from_v8<'s, 'i>(
    scope: &mut v8::PinScope<'s, 'i>,
    value: v8::Local<'s, v8::Value>,
    path: &str,
) -> Result<Value, BindingError> {
    if value.is_null_or_undefined() {
        return Ok(Value::Null);
    }
    if value.is_boolean() {
        return Ok(Value::Bool(value.boolean_value(scope)));
    }
    if value.is_number() {
        let number = value.number_value(scope).ok_or_else(|| {
            BindingError::value_conversion(
                format!("Could not convert JavaScript number at {path}",),
            )
        })?;
        if !number.is_finite() {
            return Err(BindingError::value_conversion(format!(
                "JavaScript number at {path} must be finite to return as JSON",
            )));
        }
        if number.fract() == 0.0
            && (-MAX_SAFE_INTEGER as f64..=MAX_SAFE_INTEGER as f64).contains(&number)
        {
            return Ok(Value::Number(Number::from(number as i64)));
        }
        return Number::from_f64(number).map(Value::Number).ok_or_else(|| {
            BindingError::value_conversion(format!(
                "Could not convert JavaScript number at {path} to JSON",
            ))
        });
    }
    if value.is_string() {
        return Ok(Value::String(value.to_rust_string_lossy(scope)));
    }
    if value.is_big_int() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript BigInt at {path} to Python JSON",
        )));
    }
    if value.is_symbol() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript Symbol at {path} to Python JSON",
        )));
    }
    if value.is_function() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript function at {path} to Python JSON",
        )));
    }
    if value.is_date() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript Date at {path} to Python JSON",
        )));
    }
    if value.is_map() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript Map at {path} to Python JSON",
        )));
    }
    if value.is_set() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript Set at {path} to Python JSON",
        )));
    }
    if value.is_reg_exp() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript RegExp at {path} to Python JSON",
        )));
    }
    if value.is_array_buffer() || value.is_array_buffer_view() {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript binary data at {path} to Python JSON",
        )));
    }
    if value.is_array() {
        let array = v8::Local::<v8::Array>::try_from(value).map_err(|_| {
            BindingError::value_conversion(format!("Could not convert JavaScript array at {path}",))
        })?;
        let mut values = Vec::with_capacity(array.length() as usize);
        for index in 0..array.length() {
            let value = array.get_index(scope, index).ok_or_else(|| {
                BindingError::value_conversion(format!(
                    "Could not read JavaScript array item at {}",
                    array_path(path, index as usize)
                ))
            })?;
            if value.is_undefined() {
                values.push(Value::Null);
            } else {
                values.push(value_from_v8(
                    scope,
                    value,
                    &array_path(path, index as usize),
                )?);
            }
        }
        return Ok(Value::Array(values));
    }
    if value.is_object() {
        let object = v8::Local::<v8::Object>::try_from(value).map_err(|_| {
            BindingError::value_conversion(
                format!("Could not convert JavaScript object at {path}",),
            )
        })?;
        let constructor_name = object.get_constructor_name().to_rust_string_lossy(scope);
        if constructor_name != "Object" {
            return Err(BindingError::value_conversion(format!(
                "Only plain JavaScript objects can be returned as Python JSON at {path}; got {constructor_name}",
            )));
        }
        let keys = object
            .get_own_property_names(
                scope,
                v8::GetPropertyNamesArgsBuilder::new()
                    .key_conversion(v8::KeyConversionMode::ConvertToString)
                    .build(),
            )
            .ok_or_else(|| {
                BindingError::value_conversion(format!(
                    "Could not enumerate JavaScript object at {path}",
                ))
            })?;
        let mut values = Map::new();
        for index in 0..keys.length() {
            let key = keys.get_index(scope, index).ok_or_else(|| {
                BindingError::value_conversion(format!(
                    "Could not read JavaScript object key at {path}",
                ))
            })?;
            let value = object.get(scope, key).ok_or_else(|| {
                BindingError::value_conversion(format!(
                    "Could not read JavaScript object value at {path}",
                ))
            })?;
            if value.is_undefined() {
                continue;
            }
            let key = key.to_rust_string_lossy(scope);
            values.insert(
                key.clone(),
                value_from_v8(scope, value, &object_path(path, &key))?,
            );
        }
        return Ok(Value::Object(values));
    }

    Err(BindingError::value_conversion(format!(
        "Cannot convert JavaScript {} at {path} to Python JSON",
        value.type_repr()
    )))
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
    use super::{MAX_SAFE_INTEGER, PyJsValue};
    use deno_core::serde_json::{Map, Number, Value};
    use pyo3::types::{PyAnyMethods, PyDict, PyDictMethods, PyList, PyListMethods, PyTuple};

    #[test]
    fn models_json_primitive_values() {
        assert_eq!(PyJsValue::from_json(Value::Null).as_json(), &Value::Null);
        assert_eq!(
            PyJsValue::from_json(Value::Bool(true)).as_json(),
            &Value::Bool(true)
        );
        assert_eq!(
            PyJsValue::from_json(Value::Number(Number::from(42))).as_json(),
            &Value::Number(Number::from(42))
        );
        assert_eq!(
            PyJsValue::from_json(Value::String("deno".to_string())).as_json(),
            &Value::String("deno".to_string())
        );
    }

    #[test]
    fn models_arrays_as_structured_values_not_serialized_strings() {
        let array = PyJsValue::from_json(Value::Array(vec![
            Value::Number(Number::from(1)),
            Value::Bool(true),
            Value::Null,
        ]));

        assert!(matches!(array.as_json(), Value::Array(values) if values.len() == 3));
    }

    #[test]
    fn models_objects_as_structured_values_not_serialized_strings() {
        let object = PyJsValue::from_json(Value::Object(Map::from_iter([(
            "answer".to_string(),
            Value::Number(Number::from(42)),
        )])));

        assert!(matches!(object.as_json(), Value::Object(values) if values.contains_key("answer")));
    }

    #[test]
    fn defines_python_to_javascript_conversion_contract() {
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item("name", "deno").expect("name should insert");
            dict.set_item("items", vec![1, 2, 3])
                .expect("items should insert");

            let value = PyJsValue::from_py(dict.as_any()).expect("dict should convert");

            assert!(matches!(value.as_json(), Value::Object(_)));
        });
    }

    #[test]
    fn preserves_python_object_key_order() {
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item("z", 1).expect("z should insert");
            dict.set_item("a", 2).expect("a should insert");

            let value = PyJsValue::from_py(dict.as_any()).expect("dict should convert");
            let Value::Object(object) = value.as_json() else {
                panic!("dict should convert to JSON object");
            };

            assert_eq!(object.keys().collect::<Vec<_>>(), ["z", "a"]);
        });
    }

    #[test]
    fn rejects_non_string_python_object_keys_with_json_path() {
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item(1, "value").expect("item should insert");

            let error = PyJsValue::from_py(dict.as_any())
                .expect_err("non-string keys should fail")
                .to_string();

            assert!(error.contains("JSON object keys must be strings"));
            assert!(error.contains("$"));
        });
    }

    #[test]
    fn rejects_non_finite_python_numbers_with_json_path() {
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item("value", f64::NAN)
                .expect("item should insert");

            let error = PyJsValue::from_py(dict.as_any())
                .expect_err("NaN should fail")
                .to_string();

            assert!(error.contains("$.value"));
            assert!(error.contains("finite"));
        });
    }

    #[test]
    fn rejects_python_ints_outside_javascript_safe_integer_range() {
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let too_large = MAX_SAFE_INTEGER + 1;

            let error = PyJsValue::from_py(
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
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let list = PyList::empty(py);
            list.append(&list).expect("cycle should append");

            let error = PyJsValue::from_py(list.as_any())
                .expect_err("cycles should fail")
                .to_string();

            assert!(error.contains("cycle"));
            assert!(error.contains("$[0]"));
        });
    }

    #[test]
    fn defines_javascript_to_python_conversion_contract() {
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let value = PyJsValue::from_json(Value::Array(vec![
                Value::Null,
                Value::Bool(true),
                Value::Number(Number::from(42)),
                Value::String("deno".to_string()),
            ]));

            let py_value = value.to_py(py).expect("value should convert to Python");

            assert!(py_value.bind(py).is_instance_of::<pyo3::types::PyList>());
        });
    }

    #[test]
    fn converts_json_integer_numbers_to_python_ints() {
        pyo3::Python::initialize();
        pyo3::Python::attach(|py| {
            let value = PyJsValue::from_json(Value::Number(Number::from(42)));

            let py_value = value.to_py(py).expect("value should convert to Python");

            assert!(py_value.bind(py).extract::<i64>().is_ok());
        });
    }

    #[test]
    fn bridges_json_values_through_v8() {
        let mut runtime = deno_core::JsRuntime::new(Default::default());
        deno_core::scope!(scope, &mut runtime);
        let value = PyJsValue::from_json(Value::Object(Map::from_iter([
            ("first".to_string(), Value::Number(Number::from(1))),
            (
                "items".to_string(),
                Value::Array(vec![Value::Bool(true), Value::Null]),
            ),
        ])));

        let v8_value = value.to_v8(scope).expect("JSON should convert to V8");
        let round_trip = PyJsValue::from_v8(scope, v8_value).expect("V8 should convert to JSON");

        assert_eq!(round_trip.as_json(), value.as_json());
    }

    #[test]
    fn rejects_javascript_values_that_cannot_round_trip_to_python() {
        let error = crate::types::error::BindingError::value_conversion(
            "Cannot convert JavaScript BigInt values to Python JSON",
        );

        assert!(error.message().contains("BigInt"));
    }
}
