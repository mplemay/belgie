from __future__ import annotations

from pathlib import Path

import pytest

from belgie._pyproject import PyprojectError, parse_tool_table, read_pyproject_toml, resolve_file_dependency_paths
from belgie.mcp._builder import (
    MCP_BUILD_DEPENDENCIES_TABLE,
    MCP_PACKAGE_DIR,
    MCP_PYPROJECT_PATH,
    _load_build_dependencies,
)


def test_load_build_dependencies_reads_package_pyproject() -> None:
    dependencies = _load_build_dependencies()

    assert "@belgie/widget" in dependencies
    assert dependencies["react"] == "npm:react@^19"
    widget_dependency = dependencies["@belgie/widget"]
    assert widget_dependency.startswith("file:")
    assert (MCP_PACKAGE_DIR / "_widget_package").resolve().as_posix() in widget_dependency


def test_load_build_dependencies_rejects_missing_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    monkeypatch.setattr("belgie.mcp._builder.MCP_PYPROJECT_PATH", pyproject_path)

    with pytest.raises(PyprojectError, match="must define at least one entry"):
        _load_build_dependencies()


def test_load_build_dependencies_rejects_invalid_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """
[tool.belgie.mcp.build-dependencies]
react = ["npm:react@^19"]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("belgie.mcp._builder.MCP_PYPROJECT_PATH", pyproject_path)

    with pytest.raises(PyprojectError, match="entries must map non-empty strings"):
        _load_build_dependencies()


def test_parse_tool_table_reads_nested_mcp_dependencies() -> None:
    document = read_pyproject_toml(MCP_PYPROJECT_PATH)

    dependencies = parse_tool_table(document, *MCP_BUILD_DEPENDENCIES_TABLE)

    assert dependencies["vite"] == "npm:vite@6.1.0"
    assert dependencies["@belgie/widget"] == "file:./_widget_package"


def test_resolve_file_dependency_paths_makes_paths_absolute(tmp_path: Path) -> None:
    package_dir = tmp_path / "mcp"
    widget_dir = package_dir / "_widget_package"
    widget_dir.mkdir(parents=True)

    resolved = resolve_file_dependency_paths(
        {"@belgie/widget": "file:./_widget_package", "react": "npm:react@^19"},
        package_dir,
    )

    assert resolved["react"] == "npm:react@^19"
    assert resolved["@belgie/widget"] == f"file:{widget_dir.resolve().as_posix()}"


def test_resolve_file_dependency_paths_rejects_empty_file_path(tmp_path: Path) -> None:
    with pytest.raises(PyprojectError, match="non-empty file: path"):
        resolve_file_dependency_paths({"local": "file:"}, tmp_path)


def test_read_pyproject_toml_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PyprojectError, match="No pyproject.toml found"):
        read_pyproject_toml(tmp_path / "pyproject.toml")
