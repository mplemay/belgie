from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_pyproject_cli_example_resolves_dependency_alias(pyproject_cli_module) -> None:
    assert pyproject_cli_module.resolve_join_export() == "join"
