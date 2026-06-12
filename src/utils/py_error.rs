use pyo3::{
    PyErr,
    exceptions::{PyTypeError, PyValueError},
};

use crate::exceptions::{BelgieJavaScriptError, BelgieModuleError, BelgieRuntimeError};
use crate::types::error::BindingError;

pub(crate) fn from_binding_error(error: BindingError) -> PyErr {
    match error {
        BindingError::ValueConversion { message } => {
            if message.contains("BigInt") || message.contains("Symbol") {
                PyTypeError::new_err(message)
            } else {
                PyValueError::new_err(message)
            }
        }
        BindingError::Runtime { message } => BelgieRuntimeError::new_err(message),
        BindingError::ModuleLoad { message } => BelgieModuleError::new_err(message),
        BindingError::MissingRunExport { .. } | BindingError::NonFunctionRunExport { .. } => {
            BelgieModuleError::new_err(error.message())
        }
        BindingError::JavaScript { .. } => BelgieJavaScriptError::new_err(error.message()),
    }
}
