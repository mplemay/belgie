from __future__ import annotations

import sys
from pathlib import Path

import pytest

from belgie.dependencies import lock

pytestmark = pytest.mark.integration


@pytest.fixture
def jsr_deps_module(jsr_deps_example_dir: Path):
    src_dir = jsr_deps_example_dir / "src"
    sys.path.insert(0, str(src_dir))
    try:
        import jsr_deps.__main__ as jsr_deps_main  # noqa: PLC0415

        yield jsr_deps_main
    finally:
        sys.path.remove(str(src_dir))


def test_jsr_deps_example_locks_packages(jsr_deps_example_dir: Path) -> None:
    result = lock(cwd=jsr_deps_example_dir)

    assert (jsr_deps_example_dir / "deno.lock").exists()
    assert result.groups == {"default": 1}


def test_jsr_deps_example_resolves_jsr_import(jsr_deps_module) -> None:
    assert jsr_deps_module.resolve_join_export() == "join"
