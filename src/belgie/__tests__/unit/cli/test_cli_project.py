from __future__ import annotations

from pathlib import Path

import pytest
import rtoml

from belgie.cli._project import (
    ProjectError,
    discover_project,
    load_project,
    preserve_file_on_error,
    set_dependency_in_document,
    write_pyproject_document,
)


def write_pyproject(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


def write_and_fail(path: Path, *, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    msg = "write failed"
    raise RuntimeError(msg)


def test_load_project_reads_tool_belgie_dependencies(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[project]
name = "demo"

[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1"
camelcase = "npm:camelcase@8.0.0"
""",
    )

    project = load_project(tmp_path)

    assert project.root == tmp_path.resolve()
    assert project.dependencies == {
        "std_path": "jsr:@std/path@^1",
        "camelcase": "npm:camelcase@8.0.0",
    }
    assert project.source == Path()
    assert project.lockfile_path == tmp_path / "deno.lock"


def test_discover_project_walks_up_to_nearest_pyproject(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[project]\nname = "demo"\n')
    nested = tmp_path / "src" / "demo"
    nested.mkdir(parents=True)

    project = discover_project(start=nested)

    assert project.root == tmp_path.resolve()
    assert project.dependencies == {}
    assert project.source == Path()


def test_load_project_reads_tool_belgie_source(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[project]
name = "demo"

[tool.belgie]
source = "src/app/widgets"
""",
    )

    project = load_project(tmp_path)

    assert project.source == Path("src/app/widgets")


def test_set_dependency_creates_tool_tables() -> None:
    document: dict[str, object] = {"project": {"name": "demo"}}

    set_dependency_in_document(document, "std_path", "jsr:@std/path@^1")

    assert document["tool"] == {
        "belgie": {
            "dependencies": {
                "std_path": "jsr:@std/path@^1",
            },
        },
    }


def test_load_project_rejects_invalid_dependency_entries(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[project]
name = "demo"

[tool.belgie.dependencies]
std_path = ["jsr:@std/path@^1"]
""",
    )

    with pytest.raises(ProjectError, match="entries must map"):
        load_project(tmp_path)


def test_write_pyproject_document_round_trips_with_rtoml(tmp_path: Path) -> None:
    document: dict[str, object] = {"project": {"name": "demo"}}
    set_dependency_in_document(document, "std_path", "jsr:@std/path@^1")

    write_pyproject_document(tmp_path, document)

    assert rtoml.load(tmp_path / "pyproject.toml") == document


def test_preserve_file_on_error_keeps_new_contents_on_success(tmp_path: Path) -> None:
    path = tmp_path / "deno.lock"
    path.write_text("original", encoding="utf-8")

    with preserve_file_on_error(path):
        path.write_text("updated", encoding="utf-8")

    assert path.read_text(encoding="utf-8") == "updated"


def test_preserve_file_on_error_restores_prior_bytes_on_error(tmp_path: Path) -> None:
    path = tmp_path / "deno.lock"
    path.write_text("original", encoding="utf-8")

    with pytest.raises(RuntimeError, match="write failed"), preserve_file_on_error(path):
        write_and_fail(path, text="updated")

    assert path.read_text(encoding="utf-8") == "original"


def test_preserve_file_on_error_removes_created_file_on_error(tmp_path: Path) -> None:
    path = tmp_path / "deno.lock"

    with pytest.raises(RuntimeError, match="write failed"), preserve_file_on_error(path):
        write_and_fail(path, text="new")

    assert not path.is_file()
