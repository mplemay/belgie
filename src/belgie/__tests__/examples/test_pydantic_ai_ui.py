from __future__ import annotations

import pytest
from fastapi import FastAPI
from pydantic_ai import Agent

pytestmark = pytest.mark.integration


def test_pydantic_ai_ui_example_defines_fastapi_app(pydantic_ai_ui_module) -> None:
    assert isinstance(pydantic_ai_ui_module.app, FastAPI)
    assert isinstance(pydantic_ai_ui_module.agent, Agent)
    assert pydantic_ai_ui_module.SANDBOX_TIMEOUT_SECONDS == 30.0
    assert pydantic_ai_ui_module.MAX_OUTPUT_BYTES == 512 * 1024
    assert any(route.path == "/api/generate" for route in pydantic_ai_ui_module.app.routes)
