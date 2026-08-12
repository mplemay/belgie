#[derive(Clone, Debug)]
pub enum BindingError {
    Runtime { message: String },
    ModuleLoad { message: String },
    MissingRunExport { context: String },
    NonFunctionRunExport { context: String },
    JavaScript { message: String },
    ValueConversion { message: String },
    Argument { message: String },
}

impl BindingError {
    pub fn runtime(message: impl Into<String>) -> Self {
        Self::Runtime {
            message: message.into(),
        }
    }

    pub fn module_load(message: impl Into<String>) -> Self {
        Self::ModuleLoad {
            message: message.into(),
        }
    }

    pub fn missing_run_export(context: impl Into<String>) -> Self {
        Self::MissingRunExport {
            context: context.into(),
        }
    }

    pub fn non_function_run_export(context: impl Into<String>) -> Self {
        Self::NonFunctionRunExport {
            context: context.into(),
        }
    }

    pub fn javascript(message: impl Into<String>) -> Self {
        Self::JavaScript {
            message: message.into(),
        }
    }

    pub fn value_conversion(message: impl Into<String>) -> Self {
        Self::ValueConversion {
            message: message.into(),
        }
    }

    pub fn argument(message: impl Into<String>) -> Self {
        Self::Argument {
            message: message.into(),
        }
    }

    pub fn message(&self) -> String {
        match self {
            Self::Runtime { message } => message.clone(),
            Self::ModuleLoad { message } => message.clone(),
            Self::MissingRunExport { context } => {
                format!("Script does not export a callable run function: {context}")
            }
            Self::NonFunctionRunExport { context } => {
                format!("Script run export is not callable: {context}")
            }
            Self::JavaScript { message } => message.clone(),
            Self::ValueConversion { message } => message.clone(),
            Self::Argument { message } => message.clone(),
        }
    }
}
