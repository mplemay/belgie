from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def simple_module(simple_example_dir: Path):
    src_dir = simple_example_dir / "src"
    sys.path.insert(0, str(src_dir))
    try:
        import simple.__main__ as simple_main  # noqa: PLC0415

        yield simple_main
    finally:
        sys.path.remove(str(src_dir))


async def test_simple_example_greets_with_async_runtime(simple_module) -> None:
    assert await simple_module.greet("belgie") == "Hello, belgie!"
