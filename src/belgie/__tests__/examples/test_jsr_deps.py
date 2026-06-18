from __future__ import annotations

import pytest

from belgie.__tests__.examples.conftest import EXAMPLES_ROOT
from belgie.dependencies import lock

pytestmark = pytest.mark.integration


def test_jsr_deps_example_locks_packages() -> None:
    lock(cwd=EXAMPLES_ROOT / "jsr-deps")


def test_jsr_deps_example_resolves_jsr_import(jsr_deps_module) -> None:
    assert jsr_deps_module.resolve_join_export() == "join"
