use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use deno_core::{JsRuntime, RuntimeOptions, FastString};
use std::sync::Arc;
use tokio::sync::Mutex;
use once_cell::sync::Lazy;

// Global Tokio runtime for executing JavaScript
static TOKIO_RT: Lazy<tokio::runtime::Runtime> = Lazy::new(|| {
    tokio::runtime::Runtime::new().expect("Failed to create Tokio runtime")
});

#[pyclass(unsendable)]
struct Runtime {
    runtime: Arc<Mutex<JsRuntime>>,
}

#[pymethods]
impl Runtime {
    #[new]
    fn new() -> Self {
        // Create a basic runtime without custom extensions
        let runtime = JsRuntime::new(RuntimeOptions::default());

        Runtime {
            runtime: Arc::new(Mutex::new(runtime)),
        }
    }

    fn __call__(
        &self,
        code: String,
    ) -> PyResult<String> {
        // Use the global Tokio runtime
        let runtime = self.runtime.clone();

        TOKIO_RT.block_on(async move {
            let mut js_rt = runtime.lock().await;

            // Execute the code
            match js_rt.execute_script("<runtime>", FastString::from(code.clone())) {
                Ok(_) => {
                    // For now, return a placeholder
                    // TODO: Extract actual result from V8
                    Ok("executed".to_string())
                }
                Err(js_error) => {
                    // Format the full error with stack trace
                    Err(PyRuntimeError::new_err(format!("JavaScript Error: {}", js_error)))
                }
            }
        })
    }
}

#[pymodule]
mod _core {
    use super::*;

    #[pymodule_export]
    use super::Runtime;

    #[pyfunction]
    fn hello_from_bin() -> String {
        "Hello from auth!".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_runtime_creation() {
        let _runtime = Runtime::new();
        // Should not panic
    }

    #[tokio::test]
    async fn test_simple_expression() {
        let runtime = Runtime::new();
        let mut rt = runtime.runtime.lock().await;

        let result = rt.execute_script("<test>", "1 + 1");
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_javascript_error() {
        let runtime = Runtime::new();
        let mut rt = runtime.runtime.lock().await;

        let result = rt.execute_script("<test>", "throw new Error('test error')");
        assert!(result.is_err());

        if let Err(e) = result {
            let msg = format!("{}", e);
            assert!(msg.contains("test error"));
        }
    }

    #[tokio::test]
    async fn test_stateful_execution() {
        let runtime = Runtime::new();
        let mut rt = runtime.runtime.lock().await;

        // Set a variable
        rt.execute_script("<test>", "var x = 42").unwrap();

        // Access it in next call
        let result = rt.execute_script("<test>", "x * 2");
        assert!(result.is_ok());
    }
}
