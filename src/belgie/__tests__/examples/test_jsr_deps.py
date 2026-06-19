from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_jsr_deps_example_resolves_jsr_import(jsr_deps_module) -> None:
    assert jsr_deps_module.resolve_join_export() == "join"
