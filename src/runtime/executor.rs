use crate::{
    runtime::DenoExecutionHandle,
    types::runner::{AsyncRunnerResult, RunnerArguments, SyncRunnerResult},
    utils::py_error,
};
use pyo3::Python;

pub(crate) fn execute_sync(
    py: Python<'_>,
    handle: &DenoExecutionHandle,
    arguments: RunnerArguments,
) -> SyncRunnerResult {
    let value = py
        .detach(|| handle.invoke_blocking(arguments))
        .map_err(py_error::from_binding_error)?;
    value.to_py(py)
}

pub(crate) async fn execute_async(
    handle: DenoExecutionHandle,
    arguments: RunnerArguments,
) -> AsyncRunnerResult {
    let mut guard = ExecutionCancellationGuard::new(handle.clone());
    let result = handle.invoke_async(arguments).await;
    guard.disarm();
    result
        .map_err(py_error::from_binding_error)
        .and_then(|value| Python::attach(|py| value.to_py(py)))
}

struct ExecutionCancellationGuard {
    handle: DenoExecutionHandle,
    armed: bool,
}

impl ExecutionCancellationGuard {
    fn new(handle: DenoExecutionHandle) -> Self {
        Self {
            handle,
            armed: true,
        }
    }

    fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for ExecutionCancellationGuard {
    fn drop(&mut self) {
        if self.armed {
            self.handle.cancel();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{execute_async, execute_sync};
    use crate::{
        options::{RuntimeOptions, ScriptOptions},
        runtime::{BoundRuntime, DenoExecutionHandle, DenoRuntime},
        script::ScriptSource,
        types::runner::RunnerArguments,
    };
    use pyo3::{
        Python,
        types::{PyDict, PyDictMethods, PyTuple},
    };
    use std::{
        env, fs, io,
        path::{Path, PathBuf},
        time::{SystemTime, UNIX_EPOCH},
    };

    fn with_python<R>(test: impl FnOnce(Python<'_>) -> R) -> R {
        Python::initialize();
        Python::attach(test)
    }

    fn empty_arguments() -> RunnerArguments {
        with_python(|py| {
            let args = PyTuple::empty(py);
            RunnerArguments::from_py(&args, None).expect("empty args should convert")
        })
    }

    fn input_arguments() -> RunnerArguments {
        with_python(|py| {
            let args = PyTuple::new(py, [41i32]).expect("tuple should build");
            let kwargs = PyDict::new(py);
            kwargs
                .set_item("label", "deno")
                .expect("keyword should be inserted");
            RunnerArguments::from_py(&args, Some(&kwargs)).expect("input args should convert")
        })
    }

    fn handle(bound: BoundRuntime) -> DenoExecutionHandle {
        DenoExecutionHandle::new(bound)
    }

    fn bound_inline(source: &str) -> BoundRuntime {
        let cwd = env::current_dir().expect("current dir should be available");
        let runtime = DenoRuntime::new(RuntimeOptions::new(cwd));
        let script = ScriptSource::from_options(ScriptOptions::inline(source.to_string()));
        runtime.bind(script)
    }

    fn bound_file(path: PathBuf, source: &str) -> BoundRuntime {
        let cwd = path
            .parent()
            .expect("test file should have a parent")
            .to_path_buf();
        let runtime = DenoRuntime::new(RuntimeOptions::new(cwd));
        let script = ScriptSource::from_options(ScriptOptions::from_file(source.to_string(), path));
        runtime.bind(script)
    }

    fn temp_dir(name: &str) -> io::Result<PathBuf> {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock should be after the Unix epoch")
            .as_nanos();
        let path = env::temp_dir().join(format!(
            "belgie-executor-{name}-{}-{nanos}",
            std::process::id()
        ));
        fs::create_dir_all(&path)?;
        Ok(path)
    }

    fn remove_dir(path: &Path) {
        let _ = fs::remove_dir_all(path);
    }

    #[test]
    fn sync_executor_runs_default_export_from_inline_script() {
        let bound = bound_inline("export default function run() { return 'ok'; }");
        let handle = handle(bound);

        let result = with_python(|py| execute_sync(py, &handle, empty_arguments()));

        assert!(
            result.is_ok(),
            "sync executor should run default exports instead of returning the stub error: {result:?}"
        );
    }

    #[test]
    fn sync_executor_passes_python_arguments_to_javascript_run() {
        let bound =
            bound_inline("export default function run(input, options) { return input + 1; }");
        let handle = handle(bound);

        let result = with_python(|py| execute_sync(py, &handle, input_arguments()));

        assert!(
            result.is_ok(),
            "sync executor should convert runner arguments and pass them to JS: {result:?}"
        );
    }

    #[test]
    fn sync_executor_supports_named_run_exports() {
        let bound = bound_inline("export function run() { return 42; }");
        let handle = handle(bound);

        let result = with_python(|py| execute_sync(py, &handle, empty_arguments()));

        assert!(
            result.is_ok(),
            "sync executor should fall back to a named run export: {result:?}"
        );
    }

    #[test]
    fn sync_executor_supports_typescript_source() {
        let bound = bound_inline(
            "export default function run(input: number): number { return input + 1; }",
        );
        let handle = handle(bound);

        let result = with_python(|py| execute_sync(py, &handle, input_arguments()));

        assert!(
            result.is_ok(),
            "sync executor should compile TypeScript annotations before execution: {result:?}"
        );
    }

    #[test]
    fn sync_executor_resolves_relative_imports_for_file_scripts() {
        let root = temp_dir("relative-imports").expect("temp dir should be created");
        fs::create_dir_all(root.join("lib")).expect("lib directory should be created");
        fs::write(
            root.join("lib/math.js"),
            "export function double(value) { return value * 2; }\n",
        )
        .expect("dependency should be written");
        let main = root.join("main.js");
        let source = "import { double } from './lib/math.js';\nexport default function run(input) { return double(input); }\n";
        fs::write(&main, source).expect("entrypoint should be written");
        let bound = bound_file(main, source);
        let handle = handle(bound);

        let result = with_python(|py| execute_sync(py, &handle, input_arguments()));

        remove_dir(&root);
        assert!(
            result.is_ok(),
            "sync executor should resolve imports relative to script files: {result:?}"
        );
    }

    #[test]
    fn sync_executor_preserves_module_state_within_a_bound_context() {
        let bound = bound_inline(
            "let count = 0; export default function run() { count += 1; return count; }",
        );
        let handle = handle(bound);

        let first = with_python(|py| execute_sync(py, &handle, empty_arguments()));
        let second = with_python(|py| execute_sync(py, &handle, empty_arguments()));

        assert!(
            first.is_ok() && second.is_ok(),
            "sync executor should preserve module state for repeated calls in one context: {first:?} {second:?}"
        );
    }

    #[test]
    fn sync_executor_reports_javascript_errors() {
        let bound = bound_inline(
            "export default function run() { throw new TypeError('vanilla js failed'); }",
        );
        let handle = handle(bound);

        let error = with_python(|py| execute_sync(py, &handle, empty_arguments()))
            .expect_err("throwing JS should surface as a Python error");

        assert!(
            error.to_string().contains("vanilla js failed"),
            "JS exception messages should be preserved, got {error}"
        );
    }

    #[test]
    fn closed_execution_handles_reject_new_invocations() {
        let bound = bound_inline("export default function run() { return 'ok'; }");
        let handle = handle(bound);

        handle
            .close_blocking()
            .expect("execution handle should close cleanly");
        let error = with_python(|py| execute_sync(py, &handle, empty_arguments()))
            .expect_err("closed handles should reject new calls");

        assert!(
            error.to_string().contains("closed"),
            "closed handle errors should be clear, got {error}"
        );
    }

    #[test]
    fn async_executor_awaits_top_level_await_and_async_run_exports() {
        let bound = bound_inline(
            "const resolved = await Promise.resolve(41); export default async function run() { return resolved + 1; }",
        );
        let handle = handle(bound);

        let result = pyo3_async_runtimes::tokio::get_runtime()
            .block_on(execute_async(handle, empty_arguments()));

        assert!(
            result.is_ok(),
            "async executor should await module evaluation and async run exports: {result:?}"
        );
    }

    #[test]
    fn async_executor_reports_javascript_errors() {
        let bound = bound_inline(
            "export default function run() { throw new TypeError('async js failed'); }",
        );
        let handle = handle(bound);

        let error = pyo3_async_runtimes::tokio::get_runtime()
            .block_on(execute_async(handle, empty_arguments()))
            .expect_err("throwing JS should surface as a Python error");

        assert!(
            error.to_string().contains("async js failed"),
            "JS exception messages should be preserved, got {error}"
        );
    }

    #[test]
    fn async_executor_preserves_runner_after_javascript_errors() {
        let bound = bound_inline("export default function run() { throw new TypeError('boom'); }");
        let handle = handle(bound);
        let runtime = pyo3_async_runtimes::tokio::get_runtime();

        let first = runtime.block_on(execute_async(handle.clone(), empty_arguments()));
        assert!(
            first.is_err() && first.as_ref().unwrap_err().to_string().contains("boom"),
            "first call should surface the JS error: {first:?}"
        );

        let second = runtime.block_on(execute_async(handle, empty_arguments()));
        assert!(
            second.is_err() && second.as_ref().unwrap_err().to_string().contains("boom"),
            "second call should still surface the JS error, not shut down the worker: {second:?}"
        );
    }
}
