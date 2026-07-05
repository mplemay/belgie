from __future__ import annotations

from pathlib import Path

import pytest

from belgie.cli._operations import install_project, lock_project, update_project
from belgie.cli._project import load_project

pytestmark = pytest.mark.integration


def test_pyproject_dependencies_lock_install_and_update(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie.dependencies]
"is-number" = "npm:is-number@7.0.0"
""",
        encoding="utf-8",
    )

    lock_result = lock_project(load_project(tmp_path))
    install_result = install_project(load_project(tmp_path), frozen=True)
    update_result = update_project(load_project(tmp_path), ["is-number"], latest=False)

    assert lock_result.dependencies == 1
    assert install_result.dependencies == 1
    assert (tmp_path / "deno.lock").is_file()
    assert update_result.lockfile
