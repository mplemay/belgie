use deno_ast::swc::ast::{CallExpr, Callee, Expr, Lit, Module, ModuleDecl, ModuleItem};
use deno_ast::swc::ecma_visit::{Visit, VisitWith, noop_visit_type};
use deno_ast::{MediaType, ModuleSpecifier, ParseParams, parse_module};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct ScriptDependencies {
    needs_package_loader: bool,
}

impl ScriptDependencies {
    pub(crate) fn needs_package_loader(self) -> bool {
        self.needs_package_loader
    }
}

pub(crate) fn analyze_script_dependencies(
    content: &str,
    media_type: MediaType,
) -> ScriptDependencies {
    let Some(module) = parse_script_module(content, media_type) else {
        return ScriptDependencies {
            needs_package_loader: false,
        };
    };
    let mut visitor = DependencyVisitor::default();
    collect_module_specifiers(&module, &mut visitor);
    ScriptDependencies {
        needs_package_loader: visitor.needs_package_loader,
    }
}

fn parse_script_module(content: &str, media_type: MediaType) -> Option<deno_ast::ParsedSource> {
    let specifier = ModuleSpecifier::parse("file:///belgie_inline_script.ts").ok()?;
    parse_module(ParseParams {
        specifier,
        text: content.into(),
        media_type,
        capture_tokens: false,
        scope_analysis: false,
        maybe_syntax: None,
    })
    .ok()
}

fn collect_module_specifiers(parsed: &deno_ast::ParsedSource, visitor: &mut DependencyVisitor) {
    let program = parsed.program_ref();
    let deno_ast::ProgramRef::Module(module) = program else {
        return;
    };
    collect_static_specifiers(module, visitor);
    module.visit_with(visitor);
}

fn collect_static_specifiers(module: &Module, visitor: &mut DependencyVisitor) {
    for item in &module.body {
        let ModuleItem::ModuleDecl(decl) = item else {
            continue;
        };
        match decl {
            ModuleDecl::Import(import) => visitor.visit_specifier(import.src.value.as_str()),
            ModuleDecl::ExportNamed(export) => {
                if let Some(src) = &export.src {
                    visitor.visit_specifier(src.value.as_str());
                }
            }
            ModuleDecl::ExportAll(export) => visitor.visit_specifier(export.src.value.as_str()),
            _ => {}
        }
    }
}

#[derive(Default)]
struct DependencyVisitor {
    needs_package_loader: bool,
}

impl DependencyVisitor {
    fn visit_specifier(&mut self, specifier: Option<&str>) {
        if specifier.is_some_and(is_inline_dependency_specifier) {
            self.needs_package_loader = true;
        }
    }
}

impl Visit for DependencyVisitor {
    noop_visit_type!();

    fn visit_call_expr(&mut self, call_expr: &CallExpr) {
        if matches!(call_expr.callee, Callee::Import(_)) {
            let specifier = call_expr
                .args
                .first()
                .and_then(|arg| match arg.expr.as_ref() {
                    Expr::Lit(Lit::Str(value)) if arg.spread.is_none() => value.value.as_str(),
                    _ => None,
                });
            self.visit_specifier(specifier);
        }
        call_expr.visit_children_with(self);
    }
}

fn is_inline_dependency_specifier(specifier: &str) -> bool {
    matches!(
        specifier.split_once(':').map(|(scheme, _)| scheme),
        Some("jsr" | "npm" | "http" | "https")
    )
}

#[cfg(test)]
mod tests {
    use deno_ast::MediaType;

    use super::{analyze_script_dependencies, is_inline_dependency_specifier};

    fn needs_package_loader(source: &str) -> bool {
        analyze_script_dependencies(source, MediaType::TypeScript).needs_package_loader()
    }

    #[test]
    fn detects_jsr_imports() {
        assert!(needs_package_loader(
            r#"import { assertEquals } from "jsr:@std/assert@1";"#
        ));
    }

    #[test]
    fn detects_npm_imports() {
        assert!(needs_package_loader(
            r#"import isNumber from "npm:is-number@7.0.0";"#
        ));
    }

    #[test]
    fn detects_remote_imports() {
        assert!(needs_package_loader(
            r#"import { join } from "https://deno.land/std@0.224.0/path/mod.ts";"#
        ));
    }

    #[test]
    fn detects_export_sources() {
        assert!(needs_package_loader(
            r#"export { join } from "jsr:@std/path@1";"#
        ));
        assert!(needs_package_loader(
            r#"export * from "npm:is-number@7.0.0";"#
        ));
    }

    #[test]
    fn detects_literal_dynamic_imports() {
        assert!(needs_package_loader(
            r#"export default async () => await import("npm:is-number@7.0.0");"#
        ));
    }

    #[test]
    fn ignores_local_and_bare_imports() {
        assert!(!needs_package_loader(
            r#"import { value } from "./value.ts";"#
        ));
        assert!(!needs_package_loader(r#"import { join } from "std_path";"#));
    }

    #[test]
    fn ignores_non_literal_dynamic_imports() {
        assert!(!needs_package_loader(
            r#"export default async (name) => await import(name);"#
        ));
    }

    #[test]
    fn classifies_inline_dependency_schemes() {
        assert!(is_inline_dependency_specifier("jsr:@std/path@1"));
        assert!(is_inline_dependency_specifier("npm:is-number@7.0.0"));
        assert!(is_inline_dependency_specifier("https://example.com/mod.ts"));
        assert!(is_inline_dependency_specifier("http://example.com/mod.ts"));
        assert!(!is_inline_dependency_specifier("node:fs"));
        assert!(!is_inline_dependency_specifier("./mod.ts"));
    }
}
