use deno_core::{
    serde_json::{Map, Value},
    v8,
};
use pyo3::{
    Bound, Py, PyAny, PyResult,
    types::{PyAnyMethods, PyDict, PyDictMethods, PyTuple, PyTupleMethods},
};

use crate::script::{ParamPattern, RunSignature};
use crate::types::{error::BindingError, value::PyJsValue};

pub(crate) type SyncRunnerResult = PyResult<Py<PyAny>>;
pub(crate) type AsyncRunnerResult = PyResult<Py<PyAny>>;

#[derive(Clone, Debug)]
pub(crate) struct RunnerArguments {
    positional: Vec<PyJsValue>,
    keyword: Map<String, Value>,
}

#[derive(Clone, Debug)]
pub(crate) enum CallArgument {
    Value(PyJsValue),
    Undefined,
}

#[derive(Clone, Debug)]
enum SlotState {
    Empty,
    Value(PyJsValue),
    Object(Map<String, Value>),
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

    pub(crate) fn values_for_call(
        &self,
        signature: Option<&RunSignature>,
    ) -> Result<Vec<CallArgument>, BindingError> {
        match signature {
            Some(signature) => self.map_to_signature(signature),
            None => Ok(self
                .legacy_values_for_call()
                .into_iter()
                .map(CallArgument::Value)
                .collect()),
        }
    }

    fn legacy_values_for_call(&self) -> Vec<PyJsValue> {
        let mut values = self.positional.clone();
        if !self.keyword.is_empty() {
            values.push(PyJsValue::from_json(Value::Object(self.keyword.clone())));
        }
        values
    }

    fn map_to_signature(
        &self,
        signature: &RunSignature,
    ) -> Result<Vec<CallArgument>, BindingError> {
        if signature.params.is_empty() {
            return Ok(self
                .legacy_values_for_call()
                .into_iter()
                .map(CallArgument::Value)
                .collect());
        }

        let param_count = signature.params.len();
        let mut slots = vec![SlotState::Empty; param_count];

        for (index, value) in self.positional.iter().enumerate() {
            if index >= param_count {
                return Err(BindingError::argument(format!(
                    "run() takes {param_count} positional arguments but {} were given",
                    self.positional.len()
                )));
            }
            assign_slot_value(&mut slots[index], value.clone())?;
        }

        let overflow_index = signature.overflow_param();
        let keywords = self.keyword.clone();

        for (name, value) in keywords {
            if let Some(index) = find_unfilled_ident_slot(&slots, signature, &name) {
                assign_slot_value(&mut slots[index], PyJsValue::from_json(value))?;
                continue;
            }

            if param_count == 1 {
                apply_single_param_keyword(&mut slots[0], &signature.params[0], &name, value)?;
                continue;
            }

            if let Some(index) = find_object_key_slot(&slots, signature, &name) {
                merge_object_field(&mut slots[index], &name, value)?;
                continue;
            }

            if let Some(index) = overflow_index {
                merge_overflow_keyword(&mut slots[index], &name, value)?;
                continue;
            }

            return Err(BindingError::argument(format!(
                "run() got an unexpected keyword argument '{name}'"
            )));
        }

        finalize_slots(&slots)
    }

    pub(crate) fn to_v8_globals(
        &self,
        scope: &mut v8::PinScope<'_, '_>,
        signature: Option<&RunSignature>,
    ) -> Result<Vec<v8::Global<v8::Value>>, BindingError> {
        self.values_for_call(signature)?
            .iter()
            .map(|argument| match argument {
                CallArgument::Value(value) => {
                    let local = value.to_v8(scope)?;
                    Ok(v8::Global::new(scope, local))
                }
                CallArgument::Undefined => {
                    let undefined = v8::undefined(scope).cast::<v8::Value>();
                    Ok(v8::Global::new(scope, undefined))
                }
            })
            .collect()
    }
}

fn apply_single_param_keyword(
    slot: &mut SlotState,
    param: &ParamPattern,
    name: &str,
    value: Value,
) -> Result<(), BindingError> {
    match param {
        ParamPattern::Ident {
            name: ident,
            accepts_object_fields,
        } => {
            if ident == name {
                assign_slot_value(slot, PyJsValue::from_json(value))
            } else if *accepts_object_fields {
                merge_into_slot_object(slot, name, value)
            } else {
                Err(BindingError::argument(format!(
                    "run() got an unexpected keyword argument '{name}'"
                )))
            }
        }
        ParamPattern::Object { keys, .. } if keys.iter().any(|key| key == name) => {
            merge_into_slot_object(slot, name, value)
        }
        ParamPattern::Object { .. } => merge_into_slot_object(slot, name, value),
        ParamPattern::Rest(_) => merge_overflow_keyword(slot, name, value),
    }
}

fn merge_into_slot_object(
    slot: &mut SlotState,
    name: &str,
    value: Value,
) -> Result<(), BindingError> {
    match slot {
        SlotState::Value(existing) => {
            if let Value::Object(mut object) = existing.as_json().clone() {
                if object.contains_key(name) {
                    return Err(BindingError::argument(format!(
                        "run() got multiple values for argument '{name}'"
                    )));
                }
                object.insert(name.to_string(), value);
                *slot = SlotState::Object(object);
                Ok(())
            } else {
                merge_object_field(slot, name, value)
            }
        }
        _ => merge_object_field(slot, name, value),
    }
}

fn assign_slot_value(slot: &mut SlotState, value: PyJsValue) -> Result<(), BindingError> {
    match slot {
        SlotState::Empty => {
            *slot = SlotState::Value(value);
            Ok(())
        }
        SlotState::Value(_) | SlotState::Object(_) => Err(BindingError::argument(
            "multiple values for the same script argument",
        )),
    }
}

fn find_unfilled_ident_slot(
    slots: &[SlotState],
    signature: &RunSignature,
    name: &str,
) -> Option<usize> {
    for (index, param) in signature.params.iter().enumerate() {
        if matches!(param, ParamPattern::Ident { name: ident, .. } if ident == name)
            && matches!(slots[index], SlotState::Empty)
        {
            return Some(index);
        }
    }
    None
}

fn find_object_key_slot(
    slots: &[SlotState],
    signature: &RunSignature,
    name: &str,
) -> Option<usize> {
    for (index, param) in signature.params.iter().enumerate() {
        if let ParamPattern::Object { keys, .. } = param
            && keys.iter().any(|key| key == name)
            && matches!(slots[index], SlotState::Empty | SlotState::Object(_))
        {
            return Some(index);
        }
    }
    None
}

fn merge_object_field(slot: &mut SlotState, name: &str, value: Value) -> Result<(), BindingError> {
    match slot {
        SlotState::Empty => {
            let mut object = Map::new();
            object.insert(name.to_string(), value);
            *slot = SlotState::Object(object);
            Ok(())
        }
        SlotState::Object(object) => {
            if object.contains_key(name) {
                return Err(BindingError::argument(format!(
                    "run() got multiple values for argument '{name}'"
                )));
            }
            object.insert(name.to_string(), value);
            Ok(())
        }
        SlotState::Value(_) => Err(BindingError::argument(format!(
            "run() got multiple values for argument '{name}'"
        ))),
    }
}

fn merge_overflow_keyword(
    slot: &mut SlotState,
    name: &str,
    value: Value,
) -> Result<(), BindingError> {
    match slot {
        SlotState::Empty | SlotState::Object(_) => merge_object_field(slot, name, value),
        SlotState::Value(existing) => {
            let mut object = match existing.as_json() {
                Value::Object(object) => object.clone(),
                _ => {
                    return Err(BindingError::argument(
                        "run() overflow argument must be an object",
                    ));
                }
            };
            if object.contains_key(name) {
                return Err(BindingError::argument(format!(
                    "run() got multiple values for argument '{name}'"
                )));
            }
            object.insert(name.to_string(), value);
            *slot = SlotState::Object(object);
            Ok(())
        }
    }
}

fn finalize_slots(slots: &[SlotState]) -> Result<Vec<CallArgument>, BindingError> {
    let last_filled = slots
        .iter()
        .rposition(|slot| !matches!(slot, SlotState::Empty));

    let Some(last_filled) = last_filled else {
        return Ok(Vec::new());
    };

    let mut arguments = Vec::with_capacity(last_filled + 1);
    for slot in &slots[..=last_filled] {
        arguments.push(match slot {
            SlotState::Empty => CallArgument::Undefined,
            SlotState::Value(value) => CallArgument::Value(value.clone()),
            SlotState::Object(object) => {
                CallArgument::Value(PyJsValue::from_json(Value::Object(object.clone())))
            }
        });
    }
    Ok(arguments)
}

#[cfg(test)]
mod tests {
    use super::{CallArgument, RunnerArguments};
    use crate::script::{ParamPattern, RunSignature};
    use crate::types::value::PyJsValue;
    use deno_core::serde_json::{Map, Value};
    use pyo3::{
        Python,
        types::{PyDict, PyDictMethods, PyTuple},
    };

    fn with_python<R>(test: impl FnOnce(Python<'_>) -> R) -> R {
        Python::initialize();
        Python::attach(test)
    }

    fn signature(params: Vec<ParamPattern>) -> RunSignature {
        RunSignature { params }
    }

    fn values_from(
        positional: Vec<Value>,
        keywords: Map<String, Value>,
        signature: Option<&RunSignature>,
    ) -> Vec<Value> {
        let arguments = RunnerArguments {
            positional: positional.into_iter().map(PyJsValue::from_json).collect(),
            keyword: keywords,
        };
        arguments
            .values_for_call(signature)
            .expect("values should map")
            .into_iter()
            .map(|argument| match argument {
                CallArgument::Value(value) => value.as_json().clone(),
                CallArgument::Undefined => Value::Null,
            })
            .collect()
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
    fn legacy_mapping_appends_keyword_object() {
        let values = values_from(
            vec![Value::Number(1.into()), Value::String("two".into())],
            Map::from_iter([
                ("z".to_string(), Value::Bool(true)),
                ("a".to_string(), Value::Bool(false)),
            ]),
            None,
        );

        assert_eq!(values.len(), 3);
        assert_eq!(values[0], Value::Number(1.into()));
        assert_eq!(values[1], Value::String("two".into()));
        assert_eq!(
            values[2],
            Value::Object(Map::from_iter([
                ("z".to_string(), Value::Bool(true)),
                ("a".to_string(), Value::Bool(false)),
            ]))
        );
    }

    fn ident_param(name: &str, accepts_object_fields: bool) -> ParamPattern {
        ParamPattern::Ident {
            name: name.to_string(),
            accepts_object_fields,
        }
    }

    #[test]
    fn maps_kwargs_to_named_parameters() {
        let sig = signature(vec![
            ident_param("first", false),
            ident_param("second", false),
        ]);
        let values = values_from(
            vec![],
            Map::from_iter([
                ("first".to_string(), Value::Number(1.into())),
                ("second".to_string(), Value::Number(2.into())),
            ]),
            Some(&sig),
        );

        assert_eq!(
            values,
            vec![Value::Number(1.into()), Value::Number(2.into())]
        );
    }

    #[test]
    fn maps_mixed_positional_and_kwargs() {
        let sig = signature(vec![
            ident_param("first", false),
            ident_param("second", false),
        ]);
        let values = values_from(
            vec![Value::Number(1.into())],
            Map::from_iter([("second".to_string(), Value::Number(2.into()))]),
            Some(&sig),
        );

        assert_eq!(
            values,
            vec![Value::Number(1.into()), Value::Number(2.into())]
        );
    }

    #[test]
    fn maps_single_input_param_from_kwargs() {
        let sig = signature(vec![ident_param("input", true)]);
        let values = values_from(
            vec![],
            Map::from_iter([("name".to_string(), Value::String("belgie".into()))]),
            Some(&sig),
        );

        assert_eq!(
            values,
            vec![Value::Object(Map::from_iter([(
                "name".to_string(),
                Value::String("belgie".into())
            )]))]
        );
    }

    #[test]
    fn maps_destructured_object_param_from_kwargs() {
        let sig = signature(vec![ParamPattern::Object {
            keys: vec!["name".to_string()],
            rest: None,
        }]);
        let values = values_from(
            vec![],
            Map::from_iter([("name".to_string(), Value::String("belgie".into()))]),
            Some(&sig),
        );

        assert_eq!(
            values,
            vec![Value::Object(Map::from_iter([(
                "name".to_string(),
                Value::String("belgie".into())
            )]))]
        );
    }

    #[test]
    fn maps_options_overflow() {
        let sig = signature(vec![
            ident_param("first", false),
            ident_param("second", false),
            ident_param("options", false),
        ]);
        let values = values_from(
            vec![Value::Number(1.into()), Value::String("two".into())],
            Map::from_iter([
                ("z".to_string(), Value::Bool(true)),
                ("a".to_string(), Value::Bool(false)),
            ]),
            Some(&sig),
        );

        assert_eq!(values.len(), 3);
        assert_eq!(values[0], Value::Number(1.into()));
        assert_eq!(values[1], Value::String("two".into()));
        assert_eq!(
            values[2],
            Value::Object(Map::from_iter([
                ("z".to_string(), Value::Bool(true)),
                ("a".to_string(), Value::Bool(false)),
            ]))
        );
    }

    #[test]
    fn maps_rest_overflow() {
        let sig = signature(vec![
            ident_param("first", false),
            ParamPattern::Rest("options".to_string()),
        ]);
        let values = values_from(
            vec![Value::Number(1.into())],
            Map::from_iter([("z".to_string(), Value::Bool(true))]),
            Some(&sig),
        );

        assert_eq!(values.len(), 2);
        assert_eq!(values[0], Value::Number(1.into()));
        assert_eq!(
            values[1],
            Value::Object(Map::from_iter([("z".to_string(), Value::Bool(true))]))
        );
    }

    #[test]
    fn rejects_unknown_keyword_arguments() {
        let sig = signature(vec![ident_param("first", false)]);
        let arguments = RunnerArguments {
            positional: vec![],
            keyword: Map::from_iter([("missing".to_string(), Value::Bool(true))]),
        };
        let error = arguments
            .values_for_call(Some(&sig))
            .expect_err("unknown keyword should fail");
        assert!(
            error
                .message()
                .contains("unexpected keyword argument 'missing'")
        );
    }
}
