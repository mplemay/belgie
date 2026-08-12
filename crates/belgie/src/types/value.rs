use deno_core::{
    serde_json::{Map, Number, Value},
    serde_v8, v8,
};

use crate::types::error::BindingError;

const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, PartialEq)]
pub struct JsValue {
    inner: Value,
}

impl JsValue {
    pub fn from_json(value: Value) -> Self {
        Self { inner: value }
    }

    pub fn as_json(&self) -> &Value {
        &self.inner
    }

    pub fn into_json(self) -> Value {
        self.inner
    }

    pub fn to_v8<'s, 'i>(
        &self,
        scope: &mut v8::PinScope<'s, 'i>,
    ) -> Result<v8::Local<'s, v8::Value>, BindingError> {
        serde_v8::to_v8(scope, &self.inner).map_err(|error| {
            BindingError::value_conversion(format!("Could not convert JSON value to V8: {error}",))
        })
    }

    pub fn from_v8<'s, 'i>(
        scope: &mut v8::PinScope<'s, 'i>,
        value: v8::Local<'s, v8::Value>,
    ) -> Result<Self, BindingError> {
        let mut seen = Vec::new();
        Ok(Self::from_json(value_from_v8(
            scope, value, "$", &mut seen,
        )?))
    }
}

type SeenV8Objects = Vec<v8::Global<v8::Object>>;

fn value_from_v8<'s, 'i>(
    scope: &mut v8::PinScope<'s, 'i>,
    value: v8::Local<'s, v8::Value>,
    path: &str,
    seen: &mut SeenV8Objects,
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
        let object = v8::Local::<v8::Object>::try_from(value).map_err(|_| {
            BindingError::value_conversion(format!("Could not convert JavaScript array at {path}",))
        })?;
        enter_v8_object(scope, object, path, seen)?;
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
                    seen,
                )?);
            }
        }
        let _ = seen.pop();
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
        enter_v8_object(scope, object, path, seen)?;
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
                value_from_v8(scope, value, &object_path(path, &key), seen)?,
            );
        }
        let _ = seen.pop();
        return Ok(Value::Object(values));
    }

    Err(BindingError::value_conversion(format!(
        "Cannot convert JavaScript {} at {path} to Python JSON",
        value.type_repr()
    )))
}

fn enter_v8_object<'s, 'i>(
    scope: &mut v8::PinScope<'s, 'i>,
    object: v8::Local<'s, v8::Object>,
    path: &str,
    seen: &mut SeenV8Objects,
) -> Result<(), BindingError> {
    if seen.iter().any(|seen_object| seen_object == &object) {
        return Err(BindingError::value_conversion(format!(
            "Cannot convert JavaScript data structure cycle at {path} to Python JSON",
        )));
    }
    seen.push(v8::Global::new(scope, object));
    Ok(())
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
    use super::JsValue;
    use crate::runtime::with_test_js_runtime;
    use deno_core::{
        serde_json::{Map, Number, Value},
        v8,
    };

    #[test]
    fn models_json_primitive_values() {
        assert_eq!(JsValue::from_json(Value::Null).as_json(), &Value::Null);
        assert_eq!(
            JsValue::from_json(Value::Bool(true)).as_json(),
            &Value::Bool(true)
        );
        assert_eq!(
            JsValue::from_json(Value::Number(Number::from(42))).as_json(),
            &Value::Number(Number::from(42))
        );
        assert_eq!(
            JsValue::from_json(Value::String("deno".to_string())).as_json(),
            &Value::String("deno".to_string())
        );
    }

    #[test]
    fn models_arrays_as_structured_values_not_serialized_strings() {
        let array = JsValue::from_json(Value::Array(vec![
            Value::Number(Number::from(1)),
            Value::Bool(true),
            Value::Null,
        ]));

        assert!(matches!(array.as_json(), Value::Array(values) if values.len() == 3));
    }

    #[test]
    fn models_objects_as_structured_values_not_serialized_strings() {
        let object = JsValue::from_json(Value::Object(Map::from_iter([(
            "answer".to_string(),
            Value::Number(Number::from(42)),
        )])));

        assert!(matches!(object.as_json(), Value::Object(values) if values.contains_key("answer")));
    }

    #[test]
    fn bridges_json_values_through_v8() {
        with_test_js_runtime(|runtime| {
            deno_core::scope!(scope, runtime);
            let value = JsValue::from_json(Value::Object(Map::from_iter([
                ("first".to_string(), Value::Number(Number::from(1))),
                (
                    "items".to_string(),
                    Value::Array(vec![Value::Bool(true), Value::Null]),
                ),
            ])));

            let v8_value = value.to_v8(scope).expect("JSON should convert to V8");
            let round_trip = JsValue::from_v8(scope, v8_value).expect("V8 should convert to JSON");

            assert_eq!(round_trip.as_json(), value.as_json());
        });
    }

    #[test]
    fn rejects_cyclic_javascript_objects() {
        with_test_js_runtime(|runtime| {
            deno_core::scope!(scope, runtime);
            let object = v8::Object::new(scope);
            let key = v8::String::new(scope, "self").expect("key should build");
            object
                .set(scope, key.into(), object.into())
                .expect("property should set");

            let error = JsValue::from_v8(scope, object.into())
                .expect_err("cycles should fail")
                .message()
                .to_string();

            assert!(error.contains("cycle"));
            assert!(error.contains("$.self"));
        });
    }

    #[test]
    fn rejects_cyclic_javascript_arrays() {
        with_test_js_runtime(|runtime| {
            deno_core::scope!(scope, runtime);
            let array = v8::Array::new(scope, 0);
            array
                .set_index(scope, 0, array.into())
                .expect("array item should set");

            let error = JsValue::from_v8(scope, array.into())
                .expect_err("cycles should fail")
                .message()
                .to_string();

            assert!(error.contains("cycle"));
            assert!(error.contains("$[0]"));
        });
    }

    #[test]
    fn rejects_javascript_values_that_cannot_round_trip_to_python() {
        let error = crate::types::error::BindingError::value_conversion(
            "Cannot convert JavaScript BigInt values to Python JSON",
        );

        assert!(error.message().contains("BigInt"));
    }
}
