from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.parametrize(
    "module_fixture",
    ["simple_module", "environment_module", "pydantic_ai_demo_module"],
)


def test_main_entry_point_is_sync(module_fixture: str, request: pytest.FixtureRequest) -> None:
    module = request.getfixturevalue(module_fixture)
    assert not inspect.iscoroutinefunction(module.main)
