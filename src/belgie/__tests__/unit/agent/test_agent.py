from __future__ import annotations

from belgie import agent as agent_capability
from belgie.agent import (
    DEFAULT_RUN_CODE_INSTRUCTIONS,
    LOAD_BELGIE_TOOL_NAME,
    RUN_CODE_JSON_SCHEMA,
    RUN_CODE_METADATA,
    RUN_CODE_TOOL_NAME,
    BelgieOptions,
    BelgieRuntimeSession,
    RunCodeInput,
    format_script_failure,
)


def test_public_exports_are_limited() -> None:
    assert set(agent_capability.__all__) == {
        "BelgieOptions",
        "BelgieRuntimeSession",
        "DEFAULT_RUN_CODE_INSTRUCTIONS",
        "LOAD_BELGIE_TOOL_NAME",
        "RUN_CODE_JSON_SCHEMA",
        "RUN_CODE_METADATA",
        "RUN_CODE_TOOL_NAME",
        "RunCodeInput",
        "format_script_failure",
    }
    assert BelgieOptions.__name__ == "BelgieOptions"
    assert BelgieRuntimeSession.__name__ == "BelgieRuntimeSession"
    assert RunCodeInput.__name__ == "RunCodeInput"
    assert DEFAULT_RUN_CODE_INSTRUCTIONS is agent_capability.DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "JavaScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TypeScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TSX" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "Deno" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "npm:@belgie/render" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert RUN_CODE_TOOL_NAME == "run_code"
    assert LOAD_BELGIE_TOOL_NAME == "load_belgie"
    assert isinstance(RUN_CODE_JSON_SCHEMA, dict)
    assert isinstance(RUN_CODE_METADATA, dict)
    assert callable(format_script_failure)
