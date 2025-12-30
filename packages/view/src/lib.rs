use deno_core::{FastString, JsRuntime, RuntimeOptions};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::sync::OnceLock;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

// Global V8 platform initialization
static V8_PLATFORM_INITIALIZED: OnceLock<()> = OnceLock::new();

fn ensure_v8_platform() {
    V8_PLATFORM_INITIALIZED.get_or_init(|| {
        JsRuntime::init_platform(None, false);
    });
}

// Commands that can be sent to the JavaScript runtime thread
enum RuntimeCommand {
    Execute {
        code: String,
        response_tx: oneshot::Sender<RuntimeResponse>,
    },
}

// Responses from the JavaScript runtime
enum RuntimeResponse {
    Success(String),
    Error(String),
}

#[pyclass(unsendable)]
struct Runtime {
    command_tx: mpsc::UnboundedSender<RuntimeCommand>,
}

#[pymethods]
impl Runtime {
    #[new]
    fn new() -> Self {
        // Ensure V8 platform is initialized (idempotent, thread-safe)
        ensure_v8_platform();

        let (command_tx, mut command_rx) = mpsc::unbounded_channel::<RuntimeCommand>();

        // Spawn a dedicated thread for the JsRuntime
        std::thread::spawn(move || {
            // Create a current-thread Tokio runtime for this thread (required by deno_core)
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("Failed to create Tokio runtime");

            rt.block_on(async {
                // Create the JavaScript runtime
                let mut js_runtime = JsRuntime::new(RuntimeOptions::default());

                // Process commands
                while let Some(cmd) = command_rx.recv().await {
                    match cmd {
                        RuntimeCommand::Execute { code, response_tx } => {
                            // Execute the JavaScript code
                            let result =
                                js_runtime.execute_script("<runtime>", FastString::from(code));

                            // Send the response
                            let response = match result {
                                Ok(_) => RuntimeResponse::Success("executed".to_string()),
                                Err(js_error) => RuntimeResponse::Error(format!(
                                    "JavaScript Error: {}",
                                    js_error
                                )),
                            };

                            // Ignore if receiver is dropped
                            let _ = response_tx.send(response);
                        }
                    }
                }
            });
        });

        Runtime { command_tx }
    }

    fn __call__<'py>(&self, py: Python<'py>, code: String) -> PyResult<Bound<'py, PyAny>> {
        let command_tx = self.command_tx.clone();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            // Create a oneshot channel for the response
            let (response_tx, response_rx) = oneshot::channel();

            // Send the command
            command_tx
                .send(RuntimeCommand::Execute { code, response_tx })
                .map_err(|_| PyRuntimeError::new_err("Runtime thread has terminated"))?;

            // Wait for the response
            let response = response_rx
                .await
                .map_err(|_| PyRuntimeError::new_err("Failed to receive response from runtime"))?;

            // Convert response to PyResult
            match response {
                RuntimeResponse::Success(result) => Ok(result),
                RuntimeResponse::Error(error) => Err(PyRuntimeError::new_err(error)),
            }
        })
    }
}

#[pymodule]
mod _core {
    #[pymodule_export]
    use super::Runtime;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_runtime_creation() {
        let _runtime = Runtime::new();
        // Should not panic
    }

    // Note: These tests now need to use the Runtime Python interface
    // They can't directly access the JsRuntime anymore since it's on a dedicated thread
}
