use deno_ast::ParsedSource;
use deno_graph::analysis::{
    DependencyDescriptor, DynamicArgument, DynamicTemplatePart, ModuleInfo, SpecifierWithRange,
    TypeScriptReference,
};
use deno_graph::ast::ParserModuleAnalyzer;

use crate::packages::is_resolver_import_specifier;

pub(crate) fn content_may_have_resolver_imports(content: &str) -> bool {
    content.contains("npm:")
        || content.contains("jsr:")
        || content.contains("https:")
        || content.contains("http:")
}

pub(crate) fn analyze_parsed_script_dependencies(parsed: &ParsedSource) -> bool {
    module_needs_package_loader(&ParserModuleAnalyzer::module_info(parsed))
}

fn module_needs_package_loader(module_info: &ModuleInfo) -> bool {
    module_info
        .dependencies
        .iter()
        .any(dependency_needs_resolver)
        || module_info
            .ts_references
            .iter()
            .any(ts_reference_needs_resolver)
        || module_info
            .jsdoc_imports
            .iter()
            .any(|import| specifier_with_range_needs_resolver(&import.specifier))
        || module_info
            .self_types_specifier
            .as_ref()
            .is_some_and(specifier_with_range_needs_resolver)
        || module_info
            .jsx_import_source
            .as_ref()
            .is_some_and(specifier_with_range_needs_resolver)
        || module_info
            .jsx_import_source_types
            .as_ref()
            .is_some_and(specifier_with_range_needs_resolver)
}

fn dependency_needs_resolver(dependency: &DependencyDescriptor) -> bool {
    match dependency {
        DependencyDescriptor::Static(dependency) => {
            specifier_needs_resolver(&dependency.specifier)
                || dependency
                    .types_specifier
                    .as_ref()
                    .is_some_and(specifier_with_range_needs_resolver)
        }
        DependencyDescriptor::Dynamic(dependency) => {
            dynamic_argument_needs_resolver(&dependency.argument)
                || dependency
                    .types_specifier
                    .as_ref()
                    .is_some_and(specifier_with_range_needs_resolver)
        }
    }
}

fn ts_reference_needs_resolver(reference: &TypeScriptReference) -> bool {
    match reference {
        TypeScriptReference::Path(specifier) => specifier_with_range_needs_resolver(specifier),
        TypeScriptReference::Types { specifier, .. } => {
            specifier_with_range_needs_resolver(specifier)
        }
    }
}

fn specifier_with_range_needs_resolver(specifier: &SpecifierWithRange) -> bool {
    specifier_needs_resolver(&specifier.text)
}

fn specifier_needs_resolver(specifier: &str) -> bool {
    is_resolver_import_specifier(specifier)
}

fn dynamic_argument_needs_resolver(argument: &DynamicArgument) -> bool {
    match argument {
        DynamicArgument::String(specifier) => specifier_needs_resolver(specifier),
        DynamicArgument::Template(parts) => parts.iter().any(|part| match part {
            DynamicTemplatePart::String { value } => specifier_needs_resolver(value),
            DynamicTemplatePart::Expr => false,
        }),
        DynamicArgument::Expr => false,
    }
}

#[cfg(test)]
mod tests {
    use deno_ast::MediaType;

    use crate::script::signature::parse_script_module;

    use super::{analyze_parsed_script_dependencies, content_may_have_resolver_imports};

    fn needs_package_loader(source: &str) -> bool {
        if !content_may_have_resolver_imports(source) {
            return false;
        }
        let Some(parsed) = parse_script_module(source, MediaType::TypeScript) else {
            return false;
        };
        analyze_parsed_script_dependencies(&parsed)
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
    fn detects_require_calls() {
        assert!(needs_package_loader(
            r#"const isNumber = require("npm:is-number@7.0.0"); export default () => isNumber(1);"#
        ));
    }

    #[test]
    fn detects_deno_types_comments() {
        assert!(needs_package_loader(
            r#"// @deno-types="npm:@types/node"
import fs from "node:fs";
export default () => typeof fs.readFileSync;"#,
        ));
    }

    #[test]
    fn detects_import_type_from_jsr() {
        assert!(needs_package_loader(
            r#"import type { AssertEquals } from "jsr:@std/assert@1";
export default () => 1;"#,
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
}
