from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_simple_example_greets_with_async_runtime(simple_module) -> None:
    assert await simple_module.greet("belgie") == "Hello, belgie!"
