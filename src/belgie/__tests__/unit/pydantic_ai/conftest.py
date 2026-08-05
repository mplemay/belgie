from __future__ import annotations

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from belgie.errors import BelgieError
from belgie.pydantic_ai import _session

from .fake_belgie import FakeBelgie


@pytest.fixture
def fake_belgie(monkeypatch: pytest.MonkeyPatch) -> FakeBelgie:
    fake = FakeBelgie()
    monkeypatch.setattr(_session, "_load_belgie", lambda: fake.module)
    monkeypatch.setattr(_session, "_load_belgie_error", lambda: BelgieError)
    return fake


@pytest.fixture
def run_context() -> RunContext[None]:
    return RunContext[None](
        deps=None,
        model=TestModel(),
        usage=RunUsage(),
        prompt=None,
        messages=[],
        run_step=0,
        pending_messages=[],
    )
