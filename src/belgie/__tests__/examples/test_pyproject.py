from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_pyproject_resolves_dependency_alias(pyproject_module) -> None:
    assert pyproject_module.resolve_join_export() == "join"
