from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_pydantic_ai_example_defines_openai_agent(pydantic_ai_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    agent = pydantic_ai_module.build_agent()

    assert "Hacker News" in pydantic_ai_module.HACKER_NEWS_PROMPT
    assert agent.name is None
