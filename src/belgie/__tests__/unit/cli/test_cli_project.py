from __future__ import annotations

from pathlib import Path

import pytest
import rtoml
import tomlkit

from belgie.cli._project import (
    ProjectError,
    discover_project,
    load_project,
    preserve_file_on_error,
    set_dependency_in_document,
    update_belgie_dependencies,
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
    assert not project.module
    assert project.minimum_dependency_age is None
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
source = "src/app/views"
""",
    )

    project = load_project(tmp_path)

    assert project.source == Path("src/app/views")


def test_load_project_reads_tool_belgie_module_mode(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[project]
name = "demo"

[tool.belgie]
module = true
""",
    )

    project = load_project(tmp_path)

    assert project.module


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param('"P7D"', "P7D", id="iso-duration"),
        pytest.param('"2025-01-01T00:00:00Z"', "2025-01-01T00:00:00Z", id="timestamp"),
        pytest.param('"2025-01-01"', "2025-01-01", id="date-string"),
        pytest.param("2025-01-01", "2025-01-01", id="native-date"),
        pytest.param("2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", id="native-timestamp"),
        pytest.param("2025-01-01T00:00:00", "2025-01-01T00:00:00Z", id="native-local-datetime"),
        pytest.param("120", "120", id="minutes"),
        pytest.param("false", "0", id="disabled"),
    ],
)
def test_load_project_reads_tool_belgie_minimum_dependency_age(
    tmp_path: Path,
    value: str,
    expected: str,
) -> None:
    write_pyproject(
        tmp_path,
        f"""
[project]
name = "demo"

[tool.belgie]
minimum-dependency-age = {value}
""",
    )

    project = load_project(tmp_path)

    assert project.minimum_dependency_age == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("true", id="true"),
        pytest.param("-1", id="negative-minutes"),
        pytest.param("1.5", id="float"),
        pytest.param("[]", id="array"),
        pytest.param('""', id="empty-string"),
    ],
)
def test_load_project_rejects_invalid_tool_belgie_minimum_dependency_age(tmp_path: Path, value: str) -> None:
    write_pyproject(
        tmp_path,
        f"""
[project]
name = "demo"

[tool.belgie]
minimum-dependency-age = {value}
""",
    )

    with pytest.raises(ProjectError, match="minimum-dependency-age"):
        load_project(tmp_path)


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


def test_update_belgie_dependencies_preserves_double_quotes_and_layout(tmp_path: Path) -> None:
    original = """\
[project]
name = "demo"
authors = [
    { name = "Matt", email = "a@b.c" }
]

[tool.belgie.dependencies]
oxlint = "npm:oxlint@latest"
oxfmt = "npm:oxfmt@latest"

[tool.uv]
exclude-newer = "7 days"
"""
    write_pyproject(tmp_path, original)

    update_belgie_dependencies(
        tmp_path,
        {
            "oxlint": "npm:oxlint@^1.75.0",
            "oxfmt": "npm:oxfmt@^0.60.0",
        },
    )

    updated = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "demo"' in updated
    assert "authors = [" in updated
    assert 'oxlint = "npm:oxlint@^1.75.0"' in updated
    assert 'oxfmt = "npm:oxfmt@^0.60.0"' in updated
    assert 'exclude-newer = "7 days"' in updated
    assert "[[project.authors]]" not in updated
    assert tomlkit.parse(updated)["tool"]["belgie"]["dependencies"] == {
        "oxlint": "npm:oxlint@^1.75.0",
        "oxfmt": "npm:oxfmt@^0.60.0",
    }


def test_update_belgie_dependencies_preserves_single_quotes(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """\
[project]
name = 'demo'

[tool.belgie.dependencies]
oxfmt = 'npm:oxfmt@latest'
""",
    )

    update_belgie_dependencies(tmp_path, {"oxfmt": "npm:oxfmt@^0.60.0"})

    updated = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "name = 'demo'" in updated
    assert "oxfmt = 'npm:oxfmt@^0.60.0'" in updated


def test_update_belgie_dependencies_adds_key_without_reformatting_rest(tmp_path: Path) -> None:
    original = """\
[project]
name = "demo"

[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1"

[tool.uv]
exclude-newer = "7 days"
"""
    write_pyproject(tmp_path, original)

    update_belgie_dependencies(tmp_path, {"camelcase": "npm:camelcase@8.0.0"})

    updated = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "demo"' in updated
    assert 'std_path = "jsr:@std/path@^1"' in updated
    assert 'camelcase = "npm:camelcase@8.0.0"' in updated
    assert 'exclude-newer = "7 days"' in updated


def test_update_belgie_dependencies_updates_quoted_alias(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """\
[project]
name = "demo"

[tool.belgie.dependencies]
"@types/react" = "npm:@types/react@^19"
""",
    )

    update_belgie_dependencies(tmp_path, {"@types/react": "npm:@types/react@^20"})

    updated = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '"@types/react" = "npm:@types/react@^20"' in updated


def test_update_belgie_dependencies_creates_table_when_missing(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """\
[project]
name = "demo"
""",
    )

    update_belgie_dependencies(tmp_path, {"std_path": "jsr:@std/path@^1"})

    document = rtoml.load(tmp_path / "pyproject.toml")
    assert document["tool"]["belgie"]["dependencies"] == {"std_path": "jsr:@std/path@^1"}
    updated = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "demo"' in updated
    assert "[tool.belgie.dependencies]" in updated


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
