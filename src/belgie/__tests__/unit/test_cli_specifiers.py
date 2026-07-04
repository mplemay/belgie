from __future__ import annotations

import pytest

from belgie.cli._project import ProjectError
from belgie.cli._specifiers import manifest_dependency_value


def test_manifest_dependency_value_preserves_explicit_registry_specifiers() -> None:
    assert (
        manifest_dependency_value("std_path", "jsr:@std/path@1.2.3", current="jsr:@std/path@^1")
        == "jsr:@std/path@1.2.3"
    )


def test_manifest_dependency_value_rejects_package_name_mismatch() -> None:
    with pytest.raises(ProjectError, match="no longer resolves"):
        manifest_dependency_value("camelcase", "npm:other@1.0.0", current="8.0.0")
