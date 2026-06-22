from __future__ import annotations

from collections.abc import Callable
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


@pytest.fixture
def local_file_package() -> Callable[..., Path]:
    def create(root: Path, name: str = "local-pkg") -> Path:
        local_pkg = root / name
        local_pkg.mkdir(parents=True)
        package_json = f"""
{{
  "name": "{name}",
  "version": "1.0.0",
  "type": "module",
  "exports": "./index.js"
}}
"""
        (local_pkg / "package.json").write_text(package_json, encoding="utf-8")
        (local_pkg / "index.js").write_text("export const answer = 42;\n", encoding="utf-8")
        return local_pkg

    return create
