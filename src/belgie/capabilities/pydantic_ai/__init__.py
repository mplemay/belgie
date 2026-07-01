from typing import Final

PYDANTIC_AI_REQUIRED_MESSAGE: Final[str] = (
    'pydantic-ai is required for belgie.capabilities.pydantic_ai. Install it with: uv add "belgie[pydantic-ai]"'
)

try:
    from belgie.capabilities.core._run_code import DEFAULT_RUN_CODE_INSTRUCTIONS
    from belgie.capabilities.pydantic_ai._capability import BelgieCapability
except ModuleNotFoundError as import_error:
    if import_error.name in {"pydantic", "pydantic_ai"}:
        raise ImportError(PYDANTIC_AI_REQUIRED_MESSAGE) from import_error
    raise

__all__: tuple[str, ...] = (
    "DEFAULT_RUN_CODE_INSTRUCTIONS",
    "BelgieCapability",
)
