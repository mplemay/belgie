from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def isolated_project_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    process_root = tmp_path / "process"
    process_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(process_root)
    return project_root
