from __future__ import annotations

import pytest
from pydantic_ai import Agent

from belgie.pydantic_ai import BelgieSandbox

pytestmark = pytest.mark.integration


def test_pydantic_ai_example_defines_openai_agent(pydantic_ai_module) -> None:
    assert isinstance(pydantic_ai_module.agent, Agent)
    assert pydantic_ai_module.agent.name is None
    capabilities: list[object] = []
    pydantic_ai_module.agent.root_capability.apply(capabilities.append)
    assert any(isinstance(capability, BelgieSandbox) for capability in capabilities)
