from typing import Any, Final

from pydantic import BaseModel, Field, TypeAdapter

from belgie.widget import WidgetBundle


class BuildWidgetInput(BaseModel):
    widget: str = Field(description="The complete TSX source for the virtual widget.tsx entry module.")
    files: dict[str, str] = Field(
        default_factory=dict,
        description="Optional POSIX-relative virtual text files imported by widget.tsx.",
    )


BUILD_WIDGET_TOOL_NAME: Final[str] = "build_widget"
BUILD_WIDGET_ADAPTER: Final[TypeAdapter[BuildWidgetInput]] = TypeAdapter(BuildWidgetInput)
BUILD_WIDGET_JSON_SCHEMA: Final[dict[str, Any]] = BUILD_WIDGET_ADAPTER.json_schema()
BUILD_WIDGET_ARGS_VALIDATOR: Final[Any] = BUILD_WIDGET_ADAPTER.validator
BUILD_WIDGET_METADATA: Final[dict[str, str]] = {
    "code_arg_name": "widget",
    "code_arg_language": "tsx",
}
BUILD_WIDGET_DESCRIPTION: Final[str] = """\
Build an isolated Belgie MCP widget from an in-memory TSX project.

Provide the complete default-exporting `widget.tsx` module in `widget`. Put optional local modules, CSS, JSON, and
textual assets in `files`, keyed by normalized POSIX-relative paths. Import those files with relative specifiers. Only
packages configured by the host are available. Absolute paths, URLs, and `file:`, `node:`, `deno:`, and `npm:` imports
are blocked.

The build compiles the source as data without writing or evaluating it. A successful call returns a concise summary; the
self-contained HTML is retained as application metadata/artifact rather than placed in model context.
"""
WIDGET_FAILURE_PREFIX: Final[str] = "Widget build failed:\n"


def format_widget_failure(error: Exception) -> str:
    return f"{WIDGET_FAILURE_PREFIX}{error}"


def widget_build_summary(bundle: WidgetBundle, source: BuildWidgetInput) -> str:
    file_count = len(source.files) + 1
    noun = "file" if file_count == 1 else "files"
    return f"Built widget from {file_count} virtual {noun} ({len(bundle.html.encode())} HTML bytes)."
