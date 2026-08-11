use deno_core::{serde_v8, v8};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Number, Value};

use crate::SandboxError;

pub const MAX_VALUE_DEPTH: usize = 64;
const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(transparent)]
pub struct JsValue(Value);

impl JsValue {
    pub fn from_json(value: Value) -> Result<Self, SandboxError> {
        validate_json_depth(&value, 0, "$")?;
        Ok(Self(value))
    }

    pub fn from_json_unchecked(value: Value) -> Self {
        Self(value)
    }

    pub fn as_json(&self) -> &Value {
        &self.0
    }

    pub fn into_json(self) -> Value {
        self.0
    }

    pub fn to_v8<'s, 'i>(
        &self,
        scope: &mut v8::PinScope<'s, 'i>,
    ) -> Result<v8::Local<'s, v8::Value>, SandboxError> {
        serde_v8::to_v8(scope, &self.0)
            .map_err(|error| SandboxError::value(format!("Could not convert JSON to V8: {error}")))
    }

    pub fn from_v8<'s, 'i>(
        scope: &mut v8::PinScope<'s, 'i>,
        value: v8::Local<'s, v8::Value>,
    ) -> Result<Self, SandboxError> {
        let mut seen = Vec::new();
        let value = value_from_v8(scope, value, "$", 0, &mut seen)?;
        Self::from_json(value)
    }
}

fn validate_json_depth(value: &Value, depth: usize, path: &str) -> Result<(), SandboxError> {
    if depth > MAX_VALUE_DEPTH {
        return Err(SandboxError::value(format!(
            "JSON value exceeds the maximum depth of {MAX_VALUE_DEPTH} at {path}",
        )));
    }
    match value {
        Value::Array(values) => {
            for (index, value) in values.iter().enumerate() {
                validate_json_depth(value, depth + 1, &format!("{path}[{index}]"))?;
            }
        }
        Value::Object(values) => {
            for (key, value) in values {
                validate_json_depth(value, depth + 1, &object_path(path, key))?;
            }
        }
        _ => {}
    }
    Ok(())
}

type SeenObjects = Vec<v8::Global<v8::Object>>;

fn value_from_v8<'s, 'i>(
    scope: &mut v8::PinScope<'s, 'i>,
    value: v8::Local<'s, v8::Value>,
    path: &str,
    depth: usize,
    seen: &mut SeenObjects,
) -> Result<Value, SandboxError> {
    if depth > MAX_VALUE_DEPTH {
        return Err(SandboxError::value(format!(
            "JavaScript value exceeds the maximum depth of {MAX_VALUE_DEPTH} at {path}",
        )));
    }
    if value.is_null() {
        return Ok(Value::Null);
    }
    if value.is_undefined() {
        return Err(SandboxError::value(format!(
            "Cannot convert JavaScript undefined at {path} to JSON",
        )));
    }
    if value.is_boolean() {
        return Ok(Value::Bool(value.boolean_value(scope)));
    }
    if value.is_number() {
        let number = value
            .number_value(scope)
            .ok_or_else(|| SandboxError::value(format!("Could not read number at {path}")))?;
        if !number.is_finite() {
            return Err(SandboxError::value(format!(
                "JavaScript number at {path} must be finite",
            )));
        }
        if number.fract() == 0.0
            && (-MAX_SAFE_INTEGER as f64..=MAX_SAFE_INTEGER as f64).contains(&number)
        {
            return Ok(Value::Number(Number::from(number as i64)));
        }
        return Number::from_f64(number)
            .map(Value::Number)
            .ok_or_else(|| SandboxError::value(format!("Could not convert number at {path}")));
    }
    if value.is_string() {
        return Ok(Value::String(value.to_rust_string_lossy(scope)));
    }
    reject_unsupported(value, path)?;

    if value.is_array() {
        let array = v8::Local::<v8::Array>::try_from(value)
            .map_err(|_| SandboxError::value(format!("Could not read array at {path}")))?;
        let object = v8::Local::<v8::Object>::try_from(value)
            .map_err(|_| SandboxError::value(format!("Could not read array at {path}")))?;
        enter_object(scope, object, path, seen)?;
        let mut values = Vec::with_capacity(array.length() as usize);
        for index in 0..array.length() {
            let item_path = format!("{path}[{index}]");
            let item = array.get_index(scope, index).ok_or_else(|| {
                SandboxError::value(format!("Could not read array item at {item_path}"))
            })?;
            values.push(value_from_v8(scope, item, &item_path, depth + 1, seen)?);
        }
        seen.pop();
        return Ok(Value::Array(values));
    }

    if value.is_object() {
        let object = v8::Local::<v8::Object>::try_from(value)
            .map_err(|_| SandboxError::value(format!("Could not read object at {path}")))?;
        let constructor_name = object.get_constructor_name().to_rust_string_lossy(scope);
        let has_null_prototype = object
            .get_prototype(scope)
            .is_some_and(|value| value.is_null());
        if constructor_name != "Object" && !has_null_prototype {
            return Err(SandboxError::value(format!(
                "Only plain JavaScript objects can cross the sandbox boundary at {path}; got {constructor_name}",
            )));
        }
        enter_object(scope, object, path, seen)?;
        let symbol_keys = object
            .get_own_property_names(
                scope,
                v8::GetPropertyNamesArgsBuilder::new()
                    .property_filter(v8::PropertyFilter::SKIP_STRINGS)
                    .build(),
            )
            .ok_or_else(|| {
                SandboxError::value(format!("Could not enumerate object symbols at {path}"))
            })?;
        if symbol_keys.length() != 0 {
            return Err(SandboxError::value(format!(
                "JSON objects cannot have symbol keys at {path}",
            )));
        }
        let keys = object
            .get_own_property_names(
                scope,
                v8::GetPropertyNamesArgsBuilder::new()
                    .key_conversion(v8::KeyConversionMode::ConvertToString)
                    .build(),
            )
            .ok_or_else(|| SandboxError::value(format!("Could not enumerate object at {path}")))?;
        let mut values = Map::new();
        for index in 0..keys.length() {
            let key = keys.get_index(scope, index).ok_or_else(|| {
                SandboxError::value(format!("Could not read object key at {path}"))
            })?;
            let item = object.get(scope, key).ok_or_else(|| {
                SandboxError::value(format!("Could not read object value at {path}"))
            })?;
            let key = key.to_rust_string_lossy(scope);
            let item_path = object_path(path, &key);
            values.insert(
                key,
                value_from_v8(scope, item, &item_path, depth + 1, seen)?,
            );
        }
        seen.pop();
        return Ok(Value::Object(values));
    }

    Err(SandboxError::value(format!(
        "Cannot convert JavaScript {} at {path} to JSON",
        value.type_repr(),
    )))
}

fn reject_unsupported(value: v8::Local<'_, v8::Value>, path: &str) -> Result<(), SandboxError> {
    let kind = if value.is_big_int() {
        Some("BigInt")
    } else if value.is_symbol() {
        Some("Symbol")
    } else if value.is_function() {
        Some("function")
    } else if value.is_date() {
        Some("Date")
    } else if value.is_map() {
        Some("Map")
    } else if value.is_set() {
        Some("Set")
    } else if value.is_reg_exp() {
        Some("RegExp")
    } else if value.is_array_buffer() || value.is_array_buffer_view() {
        Some("binary data")
    } else if value.is_proxy() {
        Some("Proxy")
    } else {
        None
    };
    if let Some(kind) = kind {
        return Err(SandboxError::value(format!(
            "Cannot convert JavaScript {kind} at {path} to JSON",
        )));
    }
    Ok(())
}

fn enter_object<'s, 'i>(
    scope: &mut v8::PinScope<'s, 'i>,
    object: v8::Local<'s, v8::Object>,
    path: &str,
    seen: &mut SeenObjects,
) -> Result<(), SandboxError> {
    if seen.iter().any(|seen_object| seen_object == &object) {
        return Err(SandboxError::value(format!(
            "Cannot convert a JavaScript data structure cycle at {path} to JSON",
        )));
    }
    seen.push(v8::Global::new(scope, object));
    Ok(())
}

fn object_path(path: &str, key: &str) -> String {
    if key
        .chars()
        .next()
        .is_some_and(|character| character == '_' || character.is_ascii_alphabetic())
        && key
            .chars()
            .all(|character| character == '_' || character.is_ascii_alphanumeric())
    {
        format!("{path}.{key}")
    } else {
        format!("{path}[{key:?}]")
    }
}
