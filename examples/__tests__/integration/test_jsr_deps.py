from __future__ import annotations

from pathlib import Path

import pytest

from belgie.dependencies import lock

pytestmark = pytest.mark.integration


def test_jsr_deps_example_locks_packages(jsr_deps_example_dir: Path) -> None:
    lock(cwd=jsr_deps_example_dir)


def test_jsr_deps_example_resolves_jsr_import(jsr_deps_module) -> None:
    assert jsr_deps_module.resolve_join_export() == "join"
