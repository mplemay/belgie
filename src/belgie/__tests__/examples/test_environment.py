from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def test_environment_example_resolves_jsr_import_sync(environment_module, tmp_path: Path) -> None:
    assert environment_module.resolve_join_export(tmp_path) == "join"


async def test_environment_example_resolves_jsr_import_async(environment_module, tmp_path: Path) -> None:
    assert await environment_module.resolve_join_export_async(tmp_path) == "join"
