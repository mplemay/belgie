from __future__ import annotations

import pytest
from langgraph.graph.state import CompiledStateGraph

pytestmark = pytest.mark.integration


def test_langchain_example_defines_agent(langchain_module) -> None:
    assert isinstance(langchain_module.agent, CompiledStateGraph)
