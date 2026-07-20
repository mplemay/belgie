use crate::{
    runtime::DenoExecutionHandle,
    types::runner::{AsyncRunnerResult, RunnerArguments, SyncRunnerResult},
    utils::{cancel_guard::CancelGuard, py_error},
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
    let mut guard = CancelGuard::new(handle);
    let result = guard.get().invoke_async(arguments).await;
    guard.disarm();
    result
        .map_err(py_error::from_binding_error)
        .and_then(|value| Python::attach(|py| value.to_py(py)))
}

#[cfg(test)]
mod tests {
    use super::{execute_async, execute_sync};
    use crate::{
        options::{RuntimeOptions, ScriptOptions},
        runtime::{BoundRuntime, DenoExecutionHandle, DenoRuntime, module_loader},
        script::ScriptSource,
        types::runner::RunnerArguments,
    };
    use deno_core::ModuleSpecifier;
    use deno_lib::worker::LibWorkerFactoryRoots;
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

    fn scalar_input_arguments() -> RunnerArguments {
        with_python(|py| {
            let args = PyTuple::new(py, [41i32]).expect("tuple should build");
            RunnerArguments::from_py(&args, None).expect("input args should convert")
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

    fn execute_string(handle: &DenoExecutionHandle) -> String {
        with_python(|py| {
            execute_sync(py, handle, empty_arguments())
                .expect("script should execute")
                .extract(py)
                .expect("script should return a string")
        })
    }

    fn handle(bound: BoundRuntime) -> DenoExecutionHandle {
        DenoExecutionHandle::new(bound, LibWorkerFactoryRoots::default())
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

        let result = with_python(|py| execute_sync(py, &handle, scalar_input_arguments()));

        assert!(
            result.is_ok(),
            "sync executor should compile TypeScript annotations before execution: {result:?}"
        );
    }

    #[test]
    fn sync_executor_uses_automatic_jsx_for_inline_tsx() {
        let bound = bound_inline(
            "export default function run() { return <main data-belgie=\"inline\" />; }",
        );
        let specifier = ModuleSpecifier::parse("file:///__belgie_inline__.tsx")
            .expect("inline TSX specifier should parse");
        let transpiled =
            module_loader::maybe_transpile_source(&specifier, bound.script().execution_content())
                .expect("inline TSX should transpile");

        assert!(
            transpiled.contains("npm:react@19.2.6/jsx-runtime"),
            "automatic JSX should import React's JSX runtime: {transpiled}"
        );
        assert!(
            transpiled.contains("jsx") && transpiled.contains("main"),
            "automatic JSX should lower the JSX expression: {transpiled}"
        );
    }

    #[test]
    fn renderer_context_is_frozen_read_only_and_isolated_per_script() {
        let first_source = r#"export default function run() {
  const key = Symbol.for("@belgie/render/context");
  const context = globalThis[key];
  let readOnly = false;
  try { globalThis[key] = {}; } catch { readOnly = true; }
  return [context.source.includes("first-marker"), context.url.endsWith(".ts"), Object.isFrozen(context), readOnly].join("|");
}
// first-marker"#;
        let second_source = r#"export default function run() {
  const context = globalThis[Symbol.for("@belgie/render/context")];
  return [context.source.includes("second-marker"), context.source.includes(["first", "marker"].join("-"))].join("|");
}
// second-marker"#;
        let first = handle(bound_inline(first_source));
        let second = handle(bound_inline(second_source));

        assert_eq!(execute_string(&first), "true|true|true|true");
        assert_eq!(execute_string(&second), "true|false");
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

        let result = with_python(|py| execute_sync(py, &handle, scalar_input_arguments()));

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
    fn async_executor_preserves_runner_after_javascript_errors() {
        let bound = bound_inline(
            "let count = 0; export default function run() { if (count++ === 0) throw new Error('async boom'); return 'ok'; }",
        );
        let handle = handle(bound);
        let runtime = pyo3_async_runtimes::tokio::get_runtime();

        let first = runtime.block_on(execute_async(handle.clone(), empty_arguments()));
        assert!(
            first.is_err()
                && first
                    .as_ref()
                    .unwrap_err()
                    .to_string()
                    .contains("async boom"),
            "first call should surface the JS error: {first:?}"
        );

        let second = runtime.block_on(execute_async(handle, empty_arguments()));
        assert!(
            second.is_ok(),
            "second call should succeed after disarming the cancellation guard: {second:?}"
        );
    }
}
