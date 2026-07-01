from typing import Final

LANGCHAIN_REQUIRED_MESSAGE: Final[str] = (
    'langchain is required for belgie.capabilities.langchain. Install it with: uv add "belgie[langchain]"'
)

try:
    from belgie.capabilities.core._run_code import DEFAULT_RUN_CODE_INSTRUCTIONS
    from belgie.capabilities.langchain._middleware import BelgieMiddleware
except ModuleNotFoundError as import_error:
    if import_error.name in {"langchain", "langchain_core", "langgraph"}:
        raise ImportError(LANGCHAIN_REQUIRED_MESSAGE) from import_error
    raise

__all__: tuple[str, ...] = (
    "DEFAULT_RUN_CODE_INSTRUCTIONS",
    "BelgieMiddleware",
)
