mod error;
mod runtime;
mod value;

pub use error::{SandboxError, SandboxErrorKind};
pub use runtime::{SandboxOptions, SandboxSession};
pub use value::{JsValue, MAX_VALUE_DEPTH};

#[cfg(test)]
mod tests {
    use serde_json::json;

    use crate::{JsValue, SandboxOptions, SandboxSession};

    async fn session(source: &str) -> SandboxSession {
        SandboxSession::create(source, SandboxOptions::default())
            .await
            .expect("sandbox session should bind")
    }

    #[tokio::test(flavor = "current_thread")]
    async fn executes_typescript_and_preserves_state() {
        let mut session = session(
            "let calls = 0; export default (value: number) => ({ value, calls: ++calls });",
        )
        .await;

        let first = session
            .run(vec![JsValue::from_json(json!(21)).expect("valid JSON")])
            .await
            .expect("first invocation should succeed");
        let second = session
            .run(vec![JsValue::from_json(json!(42)).expect("valid JSON")])
            .await
            .expect("second invocation should succeed");

        assert_eq!(first.into_json(), json!({"value": 21, "calls": 1}));
        assert_eq!(second.into_json(), json!({"value": 42, "calls": 2}));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn supports_async_functions_and_top_level_await() {
        let mut session = session(
            "const base: number = await Promise.resolve(40); export async function run(value: number) { return base + value; }",
        )
        .await;
        let result = session
            .run(vec![JsValue::from_json(json!(2)).expect("valid JSON")])
            .await
            .expect("invocation should succeed");
        assert_eq!(result.into_json(), json!(42));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn rejects_static_and_dynamic_imports() {
        for source in [
            "import './other.ts'; export default () => null;",
            "export default () => import('./other.ts');",
        ] {
            let error = SandboxSession::create(source, SandboxOptions::default())
                .await
                .err()
                .expect("imports should fail");
            assert_eq!(error.code, "imports_disabled");
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn does_not_install_host_globals() {
        let mut session = session(
            "export default () => ({ Deno: typeof Deno, WebAssembly: typeof WebAssembly, process: typeof process, require: typeof require, console: typeof console, queueMicrotask: typeof queueMicrotask, setTimeout: typeof setTimeout });",
        )
        .await;
        let result = session
            .run(Vec::new())
            .await
            .expect("invocation should succeed");
        assert_eq!(
            result.into_json(),
            json!({
                "Deno": "undefined",
                "WebAssembly": "undefined",
                "process": "undefined",
                "require": "undefined",
                "console": "undefined",
                "queueMicrotask": "undefined",
                "setTimeout": "undefined"
            }),
        );
    }

    #[tokio::test(flavor = "current_thread")]
    async fn rejects_unsupported_results() {
        for expression in [
            "undefined",
            "1n",
            "NaN",
            "new Date()",
            "() => 1",
            "({ [Symbol('key')]: true })",
            "new Proxy({}, {})",
        ] {
            let mut session = session(&format!("export default () => {expression};")).await;
            let error = session
                .run(Vec::new())
                .await
                .expect_err("unsupported value should fail");
            assert_eq!(error.code, "invalid_value");
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn accepts_null_prototype_json_objects() {
        let mut session =
            session("export default () => Object.assign(Object.create(null), { value: 42 });")
                .await;
        let value = session
            .run(Vec::new())
            .await
            .expect("null-prototype object should convert");
        assert_eq!(value.into_json(), json!({"value": 42}));
    }
}
