from __future__ import annotations

from pathlib import Path

import pytest

from belgie._pyproject import PyprojectError, parse_tool_table, read_pyproject_toml, resolve_file_dependency_paths
from belgie.mcp._builder import (
    _load_project_dependencies,
    _require_installed,
    _resolve_mcp_package_path,
    _resolve_project_path,
)


def test_load_project_dependencies_reads_tool_belgie_dependencies(tmp_path: Path) -> None:
    widget_dir = tmp_path / "widget"
    widget_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
"@belgie/mcp" = "file:./widget"
react = "npm:react@^19"
""".lstrip(),
        encoding="utf-8",
    )

    dependencies = _load_project_dependencies(tmp_path)

    assert dependencies["react"] == "npm:react@^19"
    assert dependencies["@belgie/mcp"] == f"file:{widget_dir.resolve().as_posix()}"


def test_load_project_dependencies_rejects_missing_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    with pytest.raises(PyprojectError, match="No \\[tool.belgie.dependencies\\] entries found"):
        _load_project_dependencies(tmp_path)


def test_load_project_dependencies_rejects_invalid_entries(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
react = ["npm:react@^19"]
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(PyprojectError, match="entries must map non-empty strings"):
        _load_project_dependencies(tmp_path)


def test_require_installed_rejects_missing_lockfile(tmp_path: Path) -> None:
    with pytest.raises(PyprojectError, match="Missing Belgie lockfile"):
        _require_installed(tmp_path)


def test_require_installed_accepts_existing_lockfile(tmp_path: Path) -> None:
    (tmp_path / "deno.lock").write_text("{}", encoding="utf-8")

    _require_installed(tmp_path)


def test_resolve_project_path_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert _resolve_project_path(None) == tmp_path.resolve()


def test_resolve_project_path_resolves_explicit_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    assert _resolve_project_path(project) == project.resolve()


def test_resolve_mcp_package_path_reads_file_dependency(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "packages" / "mcp"
    mcp_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
"@belgie/mcp" = "file:./packages/mcp"
react = "npm:react@^19"
""".lstrip(),
        encoding="utf-8",
    )

    assert _resolve_mcp_package_path(tmp_path) == mcp_dir.resolve()


def test_resolve_mcp_package_path_rejects_missing_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
react = "npm:react@^19"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(PyprojectError, match="@belgie/mcp"):
        _resolve_mcp_package_path(tmp_path)


def test_resolve_mcp_package_path_rejects_non_file_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@0.0.0"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(PyprojectError, match="must be a file: dependency"):
        _resolve_mcp_package_path(tmp_path)


def test_parse_tool_table_reads_nested_belgie_dependencies(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """
[tool.belgie.dependencies]
vite = "npm:vite@6.1.0"
"@belgie/mcp" = "file:./widget"
""".lstrip(),
        encoding="utf-8",
    )
    document = read_pyproject_toml(pyproject_path)

    dependencies = parse_tool_table(document, "belgie", "dependencies")

    assert dependencies["vite"] == "npm:vite@6.1.0"
    assert dependencies["@belgie/mcp"] == "file:./widget"


def test_resolve_file_dependency_paths_makes_paths_absolute(tmp_path: Path) -> None:
    package_dir = tmp_path / "mcp"
    widget_dir = package_dir / "packages" / "mcp"
    widget_dir.mkdir(parents=True)

    resolved = resolve_file_dependency_paths(
        {"@belgie/mcp": "file:./packages/mcp", "react": "npm:react@^19"},
        package_dir,
    )

    assert resolved["react"] == "npm:react@^19"
    assert resolved["@belgie/mcp"] == f"file:{widget_dir.resolve().as_posix()}"


def test_resolve_file_dependency_paths_rejects_empty_file_path(tmp_path: Path) -> None:
    with pytest.raises(PyprojectError, match="non-empty file: path"):
        resolve_file_dependency_paths({"local": "file:"}, tmp_path)


def test_read_pyproject_toml_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PyprojectError, match="No pyproject.toml found"):
        read_pyproject_toml(tmp_path / "pyproject.toml")
