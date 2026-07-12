from __future__ import annotations

from pathlib import Path

import pytest

from belgie._pyproject import PyprojectError, parse_tool_table, read_pyproject_toml, resolve_file_dependency_paths
from belgie.mcp._builder import (
    _load_project_dependencies,
    _normalize_base_url,
    _require_installed,
    _require_mcp_package,
    _require_render_packages,
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


def test_require_mcp_package_accepts_file_dependency(tmp_path: Path) -> None:
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

    _require_mcp_package(tmp_path)


def test_require_mcp_package_accepts_npm_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@0.1.0"
react = "npm:react@^19"
""".lstrip(),
        encoding="utf-8",
    )

    _require_mcp_package(tmp_path)


def test_require_mcp_package_rejects_missing_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
react = "npm:react@^19"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(PyprojectError, match="@belgie/mcp"):
        _require_mcp_package(tmp_path)


def test_require_render_packages_requires_mcp_and_vite(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@0.1.0"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(PyprojectError, match="vite"):
        _require_render_packages(tmp_path)

    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie.dependencies]
"@belgie/mcp" = "npm:@belgie/mcp@0.1.0"
vite = "npm:vite@8.1.3"
""".lstrip(),
        encoding="utf-8",
    )
    _require_render_packages(tmp_path)


def test_normalize_base_url_accepts_http_urls() -> None:
    assert _normalize_base_url("http://127.0.0.1:3001/") == "http://127.0.0.1:3001"


def test_normalize_base_url_rejects_relative_urls() -> None:
    with pytest.raises(ValueError, match="absolute http"):
        _normalize_base_url("/assets")


def test_parse_tool_table_reads_nested_belgie_dependencies(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """
[tool.belgie.dependencies]
vite = "npm:vite@8.1.3"
"@belgie/mcp" = "file:./widget"
""".lstrip(),
        encoding="utf-8",
    )
    document = read_pyproject_toml(pyproject_path)

    dependencies = parse_tool_table(document, "belgie", "dependencies")

    assert dependencies["vite"] == "npm:vite@8.1.3"
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
