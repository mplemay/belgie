use std::rc::Rc;

use deno_ast::swc::ast::{CallExpr, Callee, ModuleDecl, NamedExport};
use deno_ast::swc::ecma_visit::{Visit, VisitWith};
use deno_ast::{EmitOptions, ImportsNotUsedAsValues, MediaType, ParseParams, SourceMapOption};
use deno_core::error::ModuleLoaderError;
use deno_core::{
    JsRuntime, ModuleLoadOptions, ModuleLoadReferrer, ModuleLoadResponse, ModuleLoader,
    ModuleSpecifier, PollEventLoopOptions, ResolutionKind, RuntimeOptions, v8,
};

use crate::{JsValue, SandboxError};

const MAIN_MODULE: &str = "file:///__belgie_sandbox__.ts";

#[derive(Clone, Copy, Debug)]
pub struct SandboxOptions {
    pub max_old_generation_size_mb: u64,
}

impl Default for SandboxOptions {
    fn default() -> Self {
        Self {
            max_old_generation_size_mb: 128,
        }
    }
}

pub struct SandboxSession {
    runtime: JsRuntime,
    run_function: v8::Global<v8::Function>,
}

impl SandboxSession {
    pub async fn create(source: &str, options: SandboxOptions) -> Result<Self, SandboxError> {
        let specifier = ModuleSpecifier::parse(MAIN_MODULE)
            .map_err(|error| SandboxError::runtime("runtime_initialization", error.to_string()))?;
        let code = parse_and_transpile(source, &specifier)?;
        let max_heap_bytes = options
            .max_old_generation_size_mb
            .checked_mul(1024 * 1024)
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| {
                SandboxError::runtime("invalid_heap_limit", "V8 heap limit is too large")
            })?;
        let mut runtime = JsRuntime::try_new(RuntimeOptions {
            module_loader: Some(Rc::new(RejectingModuleLoader)),
            create_params: Some(v8::CreateParams::default().heap_limits(0, max_heap_bytes)),
            ..Default::default()
        })
        .map_err(|error| {
            SandboxError::runtime("runtime_initialization", error.print_with_cause())
        })?;
        remove_host_globals(&mut runtime)?;
        let module_id = runtime
            .load_main_es_module_from_code(&specifier, code)
            .await
            .map_err(|error| SandboxError::module("module_load", error.to_string()))?;
        let evaluation = runtime.mod_evaluate(module_id);
        runtime
            .run_event_loop(Default::default())
            .await
            .map_err(|error| SandboxError::javascript(error.to_string()))?;
        evaluation
            .await
            .map_err(|error| SandboxError::javascript(error.to_string()))?;
        let namespace = runtime
            .get_module_namespace(module_id)
            .map_err(|error| SandboxError::module("module_namespace", error.to_string()))?;
        let run_function = resolve_run_function(&mut runtime, namespace)?;
        Ok(Self {
            runtime,
            run_function,
        })
    }

    pub async fn run(&mut self, arguments: Vec<JsValue>) -> Result<JsValue, SandboxError> {
        let arguments = {
            deno_core::scope!(scope, self.runtime);
            arguments
                .iter()
                .map(|argument| {
                    argument
                        .to_v8(scope)
                        .map(|value| v8::Global::new(scope, value))
                })
                .collect::<Result<Vec<_>, _>>()?
        };
        let call = self.runtime.call_with_args(&self.run_function, &arguments);
        let result = self
            .runtime
            .with_event_loop_promise(call, PollEventLoopOptions::default())
            .await
            .map_err(|error| SandboxError::javascript(error.to_string()))?;
        deno_core::scope!(scope, self.runtime);
        let result = v8::Local::new(scope, result);
        JsValue::from_v8(scope, result)
    }

    pub fn isolate_handle(&mut self) -> v8::IsolateHandle {
        self.runtime.v8_isolate().thread_safe_handle()
    }

    pub fn cancel_terminate_execution(&mut self) {
        self.runtime.v8_isolate().cancel_terminate_execution();
    }
}

fn remove_host_globals(runtime: &mut JsRuntime) -> Result<(), SandboxError> {
    deno_core::scope!(scope, runtime);
    let global = scope.get_current_context().global(scope);
    for name in ["Deno", "WebAssembly", "console", "queueMicrotask"] {
        let key = v8::String::new(scope, name).ok_or_else(|| {
            SandboxError::runtime("runtime_internal", "Could not create global key")
        })?;
        if !global.delete(scope, key.into()).unwrap_or(false) {
            return Err(SandboxError::runtime(
                "runtime_initialization",
                format!("Could not remove host global {name}"),
            ));
        }
    }
    Ok(())
}

#[derive(Debug)]
struct RejectingModuleLoader;

impl ModuleLoader for RejectingModuleLoader {
    fn resolve(
        &self,
        specifier: &str,
        _referrer: &str,
        _kind: ResolutionKind,
    ) -> Result<ModuleSpecifier, ModuleLoaderError> {
        if specifier == MAIN_MODULE {
            return ModuleSpecifier::parse(specifier).map_err(deno_error::JsErrorBox::from_err);
        }
        Err(deno_error::JsErrorBox::generic(format!(
            "Imports are disabled in @belgie/runtime: {specifier}",
        )))
    }

    fn load(
        &self,
        module_specifier: &ModuleSpecifier,
        _maybe_referrer: Option<&ModuleLoadReferrer>,
        _options: ModuleLoadOptions,
    ) -> ModuleLoadResponse {
        ModuleLoadResponse::Sync(Err(deno_error::JsErrorBox::generic(format!(
            "Imports are disabled in @belgie/runtime: {module_specifier}",
        ))))
    }
}

#[derive(Default)]
struct ImportDetector {
    found: bool,
}

impl Visit for ImportDetector {
    fn visit_module_decl(&mut self, declaration: &ModuleDecl) {
        if matches!(
            declaration,
            ModuleDecl::Import(_) | ModuleDecl::ExportAll(_)
        ) || matches!(
            declaration,
            ModuleDecl::ExportNamed(NamedExport { src: Some(_), .. })
        ) {
            self.found = true;
        }
        declaration.visit_children_with(self);
    }

    fn visit_call_expr(&mut self, expression: &CallExpr) {
        if matches!(expression.callee, Callee::Import(_)) {
            self.found = true;
        }
        expression.visit_children_with(self);
    }
}

fn parse_and_transpile(source: &str, specifier: &ModuleSpecifier) -> Result<String, SandboxError> {
    let parsed = deno_ast::parse_module(ParseParams {
        specifier: specifier.clone(),
        text: source.to_string().into(),
        media_type: MediaType::TypeScript,
        capture_tokens: false,
        scope_analysis: false,
        maybe_syntax: None,
    })
    .map_err(|error| {
        SandboxError::module(
            "module_parse",
            format!("Script must be JavaScript or TypeScript; TSX is not supported: {error}"),
        )
    })?;
    let mut detector = ImportDetector::default();
    parsed.program_ref().visit_with(&mut detector);
    if detector.found {
        return Err(SandboxError::module(
            "imports_disabled",
            "Static and dynamic imports are disabled in @belgie/runtime",
        ));
    }
    let transpiled = parsed
        .transpile(
            &deno_ast::TranspileOptions {
                imports_not_used_as_values: ImportsNotUsedAsValues::Remove,
                decorators: deno_ast::DecoratorsTranspileOption::Ecma,
                ..Default::default()
            },
            &deno_ast::TranspileModuleOptions { module_kind: None },
            &EmitOptions {
                source_map: SourceMapOption::None,
                ..Default::default()
            },
        )
        .map_err(|error| SandboxError::module("module_transpile", error.to_string()))?
        .into_source();
    Ok(transpiled.text)
}

fn resolve_run_function(
    runtime: &mut JsRuntime,
    namespace: v8::Global<v8::Object>,
) -> Result<v8::Global<v8::Function>, SandboxError> {
    deno_core::scope!(scope, runtime);
    let namespace = v8::Local::new(scope, namespace);
    for name in ["default", "run"] {
        let key = v8::String::new(scope, name).ok_or_else(|| {
            SandboxError::runtime("runtime_internal", "Could not create export key")
        })?;
        if let Some(export) = namespace.get(scope, key.into()) {
            if export.is_undefined() {
                continue;
            }
            if !export.is_function() {
                if name == "default" {
                    continue;
                }
                return Err(SandboxError::module(
                    "non_function_run_export",
                    "Script run export is not callable",
                ));
            }
            let function = v8::Local::<v8::Function>::try_from(export).map_err(|_| {
                SandboxError::module(
                    "non_function_run_export",
                    "Script run export is not callable",
                )
            })?;
            return Ok(v8::Global::new(scope, function));
        }
    }
    Err(SandboxError::module(
        "missing_run_export",
        "Script must export a default function or named run function",
    ))
}
