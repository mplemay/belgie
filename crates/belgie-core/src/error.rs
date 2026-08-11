use std::fmt::{Display, Formatter};

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SandboxErrorKind {
    Runtime,
    Module,
    JavaScript,
    Value,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SandboxError {
    pub kind: SandboxErrorKind,
    pub code: String,
    pub message: String,
}

impl SandboxError {
    pub fn runtime(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self::new(SandboxErrorKind::Runtime, code, message)
    }

    pub fn module(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self::new(SandboxErrorKind::Module, code, message)
    }

    pub fn javascript(message: impl Into<String>) -> Self {
        Self::new(SandboxErrorKind::JavaScript, "javascript_error", message)
    }

    pub fn value(message: impl Into<String>) -> Self {
        Self::new(SandboxErrorKind::Value, "invalid_value", message)
    }

    fn new(kind: SandboxErrorKind, code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            kind,
            code: code.into(),
            message: message.into(),
        }
    }
}

impl Display for SandboxError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for SandboxError {}
