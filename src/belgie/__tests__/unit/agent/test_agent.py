from __future__ import annotations

from belgie import agent as agent_capability
from belgie.agent import (
    BUILD_WIDGET_JSON_SCHEMA,
    BUILD_WIDGET_METADATA,
    BUILD_WIDGET_TOOL_NAME,
    DEFAULT_RUN_CODE_INSTRUCTIONS,
    LOAD_BELGIE_TOOL_NAME,
    RUN_CODE_JSON_SCHEMA,
    RUN_CODE_METADATA,
    RUN_CODE_TOOL_NAME,
    BelgieOptions,
    BelgieRuntimeSession,
    BuildWidgetInput,
    RunCodeInput,
    format_script_failure,
    format_widget_failure,
    widget_build_summary,
)


def test_public_exports_are_limited() -> None:
    assert set(agent_capability.__all__) == {
        "BUILD_WIDGET_JSON_SCHEMA",
        "BUILD_WIDGET_METADATA",
        "BUILD_WIDGET_TOOL_NAME",
        "BelgieOptions",
        "BelgieRuntimeSession",
        "BuildWidgetInput",
        "DEFAULT_RUN_CODE_INSTRUCTIONS",
        "LOAD_BELGIE_TOOL_NAME",
        "RUN_CODE_JSON_SCHEMA",
        "RUN_CODE_METADATA",
        "RUN_CODE_TOOL_NAME",
        "RunCodeInput",
        "format_script_failure",
        "format_widget_failure",
        "widget_build_summary",
    }
    assert BelgieOptions.__name__ == "BelgieOptions"
    assert BelgieRuntimeSession.__name__ == "BelgieRuntimeSession"
    assert RunCodeInput.__name__ == "RunCodeInput"
    assert BuildWidgetInput.__name__ == "BuildWidgetInput"
    assert DEFAULT_RUN_CODE_INSTRUCTIONS is agent_capability.DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "JavaScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TypeScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TSX" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "Deno" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "npm:@belgie/render" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert RUN_CODE_TOOL_NAME == "run_code"
    assert BUILD_WIDGET_TOOL_NAME == "build_widget"
    assert LOAD_BELGIE_TOOL_NAME == "load_belgie"
    assert isinstance(RUN_CODE_JSON_SCHEMA, dict)
    assert isinstance(RUN_CODE_METADATA, dict)
    assert BUILD_WIDGET_JSON_SCHEMA["required"] == ["widget"]
    assert isinstance(BUILD_WIDGET_METADATA, dict)
    assert callable(format_script_failure)
    assert callable(format_widget_failure)
    assert callable(widget_build_summary)
