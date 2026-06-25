use std::collections::{HashMap, HashSet};

use deno_ast::swc::ast::{
    ArrowExpr, Decl, DefaultDecl, Expr, Function, KeyValuePatProp, Module, ModuleDecl, ModuleItem,
    ObjectPatProp, Param, Pat, Stmt, TsEntityName, TsType, TsTypeOperatorOp,
    TsUnionOrIntersectionType,
};
use deno_ast::{MediaType, ModuleSpecifier, ParseParams, parse_module};

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum ParamPattern {
    Ident {
        name: String,
        accepts_object_fields: bool,
    },
    Object {
        keys: Vec<String>,
        rest: Option<String>,
    },
    Rest(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RunSignature {
    pub(crate) params: Vec<ParamPattern>,
}

impl RunSignature {
    pub(crate) fn overflow_param(&self) -> Option<usize> {
        if self.params.is_empty() {
            return None;
        }
        let last = self.params.len() - 1;
        match &self.params[last] {
            ParamPattern::Rest(_) => Some(last),
            ParamPattern::Ident { name, .. } if name == "options" => Some(last),
            _ => None,
        }
    }
}

#[derive(Clone, Debug)]
enum TypeDef {
    Interface,
    Alias(TsType),
}

#[derive(Clone, Debug, Default)]
struct TypeIndex {
    types: HashMap<String, TypeDef>,
}

impl TypeIndex {
    fn collect(module: &Module) -> Self {
        let mut index = Self::default();
        for item in &module.body {
            match item {
                ModuleItem::Stmt(Stmt::Decl(decl)) => index.insert_decl(decl),
                ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export)) => {
                    index.insert_decl(&export.decl);
                }
                _ => {}
            }
        }
        index
    }

    fn insert_decl(&mut self, decl: &Decl) {
        match decl {
            Decl::TsInterface(interface) => {
                self.types
                    .insert(interface.id.sym.to_string(), TypeDef::Interface);
            }
            Decl::TsTypeAlias(alias) => {
                self.types.insert(
                    alias.id.sym.to_string(),
                    TypeDef::Alias((*alias.type_ann).clone()),
                );
            }
            _ => {}
        }
    }
}

pub(crate) fn media_type_for_script(content_path: Option<&std::path::Path>) -> MediaType {
    match content_path {
        Some(path) => MediaType::from_path(path),
        None => MediaType::TypeScript,
    }
}

pub(crate) fn parse_script_module(
    content: &str,
    media_type: MediaType,
) -> Option<deno_ast::ParsedSource> {
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

pub(crate) fn run_signature_from_parsed(parsed: &deno_ast::ParsedSource) -> Option<RunSignature> {
    let program = parsed.program_ref();
    let deno_ast::ProgramRef::Module(module) = program else {
        return None;
    };

    extract_run_signature(module)
}

fn extract_run_signature(module: &Module) -> Option<RunSignature> {
    let type_index = TypeIndex::collect(module);
    let mut default_signature = None;
    let mut named_run_signature = None;

    for item in &module.body {
        let ModuleItem::ModuleDecl(decl) = item else {
            continue;
        };
        match decl {
            ModuleDecl::ExportDefaultDecl(export) => {
                if let Some(signature) = signature_from_default_decl(&export.decl, &type_index) {
                    default_signature = Some(signature);
                }
            }
            ModuleDecl::ExportDefaultExpr(export) => {
                if let Some(signature) = signature_from_expr(&export.expr, &type_index) {
                    default_signature = Some(signature);
                }
            }
            ModuleDecl::ExportDecl(export) => {
                if let Decl::Fn(fn_decl) = &export.decl
                    && fn_decl.ident.sym == "run"
                    && let Some(signature) = signature_from_function(&fn_decl.function, &type_index)
                {
                    named_run_signature = Some(signature);
                }
            }
            _ => {}
        }
    }

    default_signature.or(named_run_signature)
}

fn signature_from_default_decl(decl: &DefaultDecl, type_index: &TypeIndex) -> Option<RunSignature> {
    match decl {
        DefaultDecl::Fn(fn_expr) => signature_from_function(&fn_expr.function, type_index),
        _ => None,
    }
}

fn signature_from_expr(expr: &Expr, type_index: &TypeIndex) -> Option<RunSignature> {
    match expr {
        Expr::Fn(fn_expr) => signature_from_function(&fn_expr.function, type_index),
        Expr::Arrow(arrow) => signature_from_arrow(arrow, type_index),
        _ => None,
    }
}

fn signature_from_function(function: &Function, type_index: &TypeIndex) -> Option<RunSignature> {
    params_from_list(&function.params, type_index)
}

fn signature_from_arrow(arrow: &ArrowExpr, type_index: &TypeIndex) -> Option<RunSignature> {
    signature_from_pats(arrow.params.iter(), type_index)
}

fn params_from_list(params: &[Param], type_index: &TypeIndex) -> Option<RunSignature> {
    signature_from_pats(params.iter().map(|param| &param.pat), type_index)
}

fn signature_from_pats<'a>(
    pats: impl IntoIterator<Item = &'a Pat>,
    type_index: &TypeIndex,
) -> Option<RunSignature> {
    let params = pats
        .into_iter()
        .map(|pat| parse_pat(pat, type_index))
        .collect::<Option<Vec<_>>>()?;
    Some(RunSignature { params })
}

fn parse_pat(pat: &Pat, type_index: &TypeIndex) -> Option<ParamPattern> {
    match pat {
        Pat::Ident(binding) => {
            let mut visiting = HashSet::new();
            Some(ParamPattern::Ident {
                name: binding.id.sym.to_string(),
                accepts_object_fields: binding.type_ann.as_ref().is_some_and(|annotation| {
                    is_object_like_type(&annotation.type_ann, type_index, &mut visiting)
                }),
            })
        }
        Pat::Object(object) => {
            let mut keys = Vec::new();
            let mut rest = None;
            for prop in &object.props {
                match prop {
                    ObjectPatProp::KeyValue(KeyValuePatProp { key, .. }) => {
                        if let Some(key) = object_pat_key_name(key) {
                            keys.push(key);
                        }
                    }
                    ObjectPatProp::Assign(assign) => keys.push(assign.key.id.sym.to_string()),
                    ObjectPatProp::Rest(rest_pat) => {
                        rest = pat_ident_name(&rest_pat.arg);
                    }
                }
            }
            Some(ParamPattern::Object { keys, rest })
        }
        Pat::Rest(rest_pat) => pat_ident_name(&rest_pat.arg).map(ParamPattern::Rest),
        Pat::Assign(assign) => parse_pat(&assign.left, type_index),
        _ => None,
    }
}

fn object_pat_key_name(key: &deno_ast::swc::ast::PropName) -> Option<String> {
    use deno_ast::swc::ast::PropName;
    match key {
        PropName::Ident(ident) => Some(ident.sym.to_string()),
        _ => None,
    }
}

fn pat_ident_name(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(binding) => Some(binding.id.sym.to_string()),
        Pat::Assign(assign) => pat_ident_name(&assign.left),
        _ => None,
    }
}

fn is_object_like_type(
    type_ann: &TsType,
    type_index: &TypeIndex,
    visiting: &mut HashSet<String>,
) -> bool {
    match type_ann {
        TsType::TsTypeLit(_) => true,
        TsType::TsTypeRef(type_ref) => {
            let Some(name) = entity_name_ident(&type_ref.type_name) else {
                return false;
            };
            resolve_named_type(&name, type_index, visiting)
        }
        TsType::TsParenthesizedType(parenthesized) => {
            is_object_like_type(&parenthesized.type_ann, type_index, visiting)
        }
        TsType::TsOptionalType(optional) => {
            is_object_like_type(&optional.type_ann, type_index, visiting)
        }
        TsType::TsTypeOperator(operator) if operator.op == TsTypeOperatorOp::ReadOnly => {
            is_object_like_type(&operator.type_ann, type_index, visiting)
        }
        TsType::TsUnionOrIntersectionType(TsUnionOrIntersectionType::TsUnionType(union)) => union
            .types
            .iter()
            .any(|member| is_object_like_type(member, type_index, visiting)),
        TsType::TsUnionOrIntersectionType(TsUnionOrIntersectionType::TsIntersectionType(
            intersection,
        )) => intersection
            .types
            .iter()
            .all(|member| is_object_like_type(member, type_index, visiting)),
        _ => false,
    }
}

fn resolve_named_type(name: &str, type_index: &TypeIndex, visiting: &mut HashSet<String>) -> bool {
    if !visiting.insert(name.to_string()) {
        return false;
    }
    let object_like = match type_index.types.get(name) {
        Some(TypeDef::Interface) => true,
        Some(TypeDef::Alias(type_ann)) => is_object_like_type(type_ann, type_index, visiting),
        None => false,
    };
    visiting.remove(name);
    object_like
}

fn entity_name_ident(name: &TsEntityName) -> Option<String> {
    match name {
        TsEntityName::Ident(ident) => Some(ident.sym.to_string()),
        TsEntityName::TsQualifiedName(_) => None,
    }
}

#[cfg(test)]
mod tests {
    use super::{ParamPattern, RunSignature, parse_script_module, run_signature_from_parsed};
    use deno_ast::MediaType;

    fn parse_ts(source: &str) -> Option<RunSignature> {
        parse_script_module(source, MediaType::TypeScript)
            .as_ref()
            .and_then(run_signature_from_parsed)
    }

    fn ident_param(name: &str, accepts_object_fields: bool) -> ParamPattern {
        ParamPattern::Ident {
            name: name.to_string(),
            accepts_object_fields,
        }
    }

    #[test]
    fn parses_default_function_parameters() {
        let signature =
            parse_ts("export default function run(first, second, options) { return null; }")
                .expect("signature should parse");

        assert_eq!(
            signature,
            RunSignature {
                params: vec![
                    ident_param("first", false),
                    ident_param("second", false),
                    ident_param("options", false),
                ],
            }
        );
        assert_eq!(signature.overflow_param(), Some(2));
    }

    #[test]
    fn parses_default_arrow_parameters() {
        let signature =
            parse_ts("export default (first, second) => first + second;").expect("should parse");

        assert_eq!(
            signature.params,
            vec![ident_param("first", false), ident_param("second", false)]
        );
    }

    #[test]
    fn parses_named_run_export() {
        let signature =
            parse_ts("export function run(name) { return name; }").expect("should parse");

        assert_eq!(signature.params, vec![ident_param("name", false)]);
    }

    #[test]
    fn prefers_default_export_over_named_run() {
        let signature = parse_ts(
            "export function run() { return 'named'; }\nexport default function run(first) { return first; }",
        )
        .expect("should parse");

        assert_eq!(signature.params, vec![ident_param("first", false)]);
    }

    #[test]
    fn parses_object_destructuring_parameter() {
        let signature = parse_ts("export default function run({ name, ...rest }) { return name; }")
            .expect("should parse");

        assert_eq!(
            signature.params,
            vec![ParamPattern::Object {
                keys: vec!["name".to_string()],
                rest: Some("rest".to_string()),
            }]
        );
    }

    #[test]
    fn parses_rest_parameter() {
        let signature = parse_ts("export default function run(first, ...options) { return null; }")
            .expect("should parse");

        assert_eq!(
            signature.params,
            vec![
                ident_param("first", false),
                ParamPattern::Rest("options".to_string())
            ]
        );
        assert_eq!(signature.overflow_param(), Some(1));
    }

    #[test]
    fn parses_object_like_input_parameter_types() {
        let cases = [
            (
                "export default function run(input: { name: string }): { greeting: string } { return { greeting: input.name }; }",
                true,
            ),
            (
                "interface Input { name: string }\nexport default function run(input: Input): { greeting: string } { return { greeting: input.name }; }",
                true,
            ),
            (
                "export interface Input { name: string }\nexport default function run(input: Input) { return input; }",
                true,
            ),
            (
                "type Input = { name: string }\nexport default function run(input: Input) { return input; }",
                true,
            ),
            (
                "interface Other { name: string }\ntype Input = Other\nexport default function run(input: Input) { return input; }",
                true,
            ),
            (
                "type Input = string\nexport default function run(input: Input) { return input; }",
                false,
            ),
            (
                "export default function run(input: Missing) { return input; }",
                false,
            ),
        ];

        for (source, accepts_object_fields) in cases {
            let signature = parse_ts(source).expect("should parse");
            assert_eq!(
                signature.params,
                vec![ident_param("input", accepts_object_fields)],
                "source: {source}",
            );
        }
    }

    #[test]
    fn returns_none_for_non_callable_default_export() {
        assert!(parse_ts("export default 42;").is_none());
    }
}
