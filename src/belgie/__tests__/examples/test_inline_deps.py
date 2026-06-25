from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_inline_deps_example_resolves_direct_imports(inline_deps_module) -> None:
    assert inline_deps_module.resolve_inline_dependencies() == {
        "assertion": "assertEquals",
        "camelcase": "inlineDeps",
        "join": "join",
    }
