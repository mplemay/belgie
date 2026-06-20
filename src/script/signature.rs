use deno_ast::swc::ast::{
    ArrowExpr, Decl, DefaultDecl, Expr, Function, KeyValuePatProp, Module, ModuleDecl, ModuleItem,
    ObjectPatProp, Param, Pat, TsType,
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

pub(crate) fn media_type_for_script(content_path: Option<&std::path::Path>) -> MediaType {
    match content_path {
        Some(path) => MediaType::from_path(path),
        None => MediaType::TypeScript,
    }
}

pub(crate) fn parse_run_signature(content: &str, media_type: MediaType) -> Option<RunSignature> {
    let specifier = ModuleSpecifier::parse("file:///belgie_inline_script.ts").ok()?;
    let parsed = parse_module(ParseParams {
        specifier,
        text: content.into(),
        media_type,
        capture_tokens: false,
        scope_analysis: false,
        maybe_syntax: None,
    })
    .ok()?;

    let program = parsed.program_ref();
    let deno_ast::ProgramRef::Module(module) = program else {
        return None;
    };

    extract_run_signature(module)
}

fn extract_run_signature(module: &Module) -> Option<RunSignature> {
    let mut default_signature = None;
    let mut named_run_signature = None;

    for item in &module.body {
        let ModuleItem::ModuleDecl(decl) = item else {
            continue;
        };
        match decl {
            ModuleDecl::ExportDefaultDecl(export) => {
                if let Some(signature) = signature_from_default_decl(&export.decl) {
                    default_signature = Some(signature);
                }
            }
            ModuleDecl::ExportDefaultExpr(export) => {
                if let Some(signature) = signature_from_expr(&export.expr) {
                    default_signature = Some(signature);
                }
            }
            ModuleDecl::ExportDecl(export) => {
                if let Decl::Fn(fn_decl) = &export.decl
                    && fn_decl.ident.sym == "run"
                    && let Some(signature) = signature_from_function(&fn_decl.function)
                {
                    named_run_signature = Some(signature);
                }
            }
            _ => {}
        }
    }

    default_signature.or(named_run_signature)
}

fn signature_from_default_decl(decl: &DefaultDecl) -> Option<RunSignature> {
    match decl {
        DefaultDecl::Fn(fn_expr) => signature_from_function(&fn_expr.function),
        _ => None,
    }
}

fn signature_from_expr(expr: &Expr) -> Option<RunSignature> {
    match expr {
        Expr::Fn(fn_expr) => signature_from_function(&fn_expr.function),
        Expr::Arrow(arrow) => signature_from_arrow(arrow),
        _ => None,
    }
}

fn signature_from_function(function: &Function) -> Option<RunSignature> {
    params_from_list(&function.params)
}

fn signature_from_arrow(arrow: &ArrowExpr) -> Option<RunSignature> {
    let params = arrow
        .params
        .iter()
        .map(parse_pat)
        .collect::<Option<Vec<_>>>()?;
    Some(RunSignature { params })
}

fn params_from_list(params: &[Param]) -> Option<RunSignature> {
    let patterns = params
        .iter()
        .map(|param| parse_pat(&param.pat))
        .collect::<Option<Vec<_>>>()?;
    Some(RunSignature { params: patterns })
}

fn parse_pat(pat: &Pat) -> Option<ParamPattern> {
    match pat {
        Pat::Ident(binding) => Some(ParamPattern::Ident {
            name: binding.id.sym.to_string(),
            accepts_object_fields: binding
                .type_ann
                .as_ref()
                .is_some_and(|annotation| is_object_like_type(&annotation.type_ann)),
        }),
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
        Pat::Assign(assign) => parse_pat(&assign.left),
        _ => None,
    }
}

fn object_pat_key_name(key: &deno_ast::swc::ast::PropName) -> Option<String> {
    use deno_ast::swc::ast::PropName;
    match key {
        PropName::Ident(ident) => Some(ident.sym.to_string()),
        PropName::Str(_) => None,
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

fn is_object_like_type(type_ann: &TsType) -> bool {
    matches!(type_ann, TsType::TsTypeLit(_))
}

#[cfg(test)]
mod tests {
    use super::{ParamPattern, RunSignature, parse_run_signature};
    use deno_ast::MediaType;

    fn parse_ts(source: &str) -> Option<RunSignature> {
        parse_run_signature(source, MediaType::TypeScript)
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
                    ParamPattern::Ident {
                        name: "first".to_string(),
                        accepts_object_fields: false,
                    },
                    ParamPattern::Ident {
                        name: "second".to_string(),
                        accepts_object_fields: false,
                    },
                    ParamPattern::Ident {
                        name: "options".to_string(),
                        accepts_object_fields: false,
                    },
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
            vec![
                ParamPattern::Ident {
                    name: "first".to_string(),
                    accepts_object_fields: false,
                },
                ParamPattern::Ident {
                    name: "second".to_string(),
                    accepts_object_fields: false,
                },
            ]
        );
    }

    #[test]
    fn parses_named_run_export() {
        let signature =
            parse_ts("export function run(name) { return name; }").expect("should parse");

        assert_eq!(
            signature.params,
            vec![ParamPattern::Ident {
                name: "name".to_string(),
                accepts_object_fields: false,
            }]
        );
    }

    #[test]
    fn prefers_default_export_over_named_run() {
        let signature = parse_ts(
            "export function run() { return 'named'; }\nexport default function run(first) { return first; }",
        )
        .expect("should parse");

        assert_eq!(
            signature.params,
            vec![ParamPattern::Ident {
                name: "first".to_string(),
                accepts_object_fields: false,
            }]
        );
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
                ParamPattern::Ident {
                    name: "first".to_string(),
                    accepts_object_fields: false,
                },
                ParamPattern::Rest("options".to_string()),
            ]
        );
        assert_eq!(signature.overflow_param(), Some(1));
    }

    #[test]
    fn parses_single_input_parameter_with_type_annotation() {
        let signature = parse_ts(
            "export default function run(input: { name: string }): { greeting: string } { return { greeting: input.name }; }",
        )
        .expect("should parse");

        assert_eq!(
            signature.params,
            vec![ParamPattern::Ident {
                name: "input".to_string(),
                accepts_object_fields: true,
            }]
        );
    }

    #[test]
    fn returns_none_for_non_callable_default_export() {
        assert!(parse_ts("export default 42;").is_none());
    }
}
