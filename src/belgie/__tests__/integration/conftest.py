from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

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


def assert_installed_package_dir(path: Path) -> None:
    assert path.is_dir()
    assert not path.is_symlink()


def _write_local_package(
    root: Path,
    name: str = "local-pkg",
    *,
    module_system: Literal["esm", "cjs"] = "esm",
) -> Path:
    local_pkg = root / name
    local_pkg.mkdir(parents=True)
    if module_system == "esm":
        package_json = {
            "name": name,
            "version": "1.0.0",
            "type": "module",
            "exports": "./index.js",
        }
        index_js = "export const answer = 42;\n"
    else:
        package_json = {
            "name": name,
            "version": "1.0.0",
            "main": "index.js",
        }
        index_js = "module.exports = { answer: 42 };\n"
    (local_pkg / "package.json").write_text(
        json.dumps(package_json, indent=2) + "\n",
        encoding="utf-8",
    )
    (local_pkg / "index.js").write_text(index_js, encoding="utf-8")
    return local_pkg


@pytest.fixture
def local_cjs_package() -> Callable[..., Path]:
    def create(root: Path, name: str = "local-pkg") -> Path:
        return _write_local_package(root, name, module_system="cjs")

    return create


@pytest.fixture
def local_file_package() -> Callable[..., Path]:
    def create(root: Path, name: str = "local-pkg") -> Path:
        return _write_local_package(root, name, module_system="esm")

    return create
