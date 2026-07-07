from __future__ import annotations

from pathlib import Path

import pytest

from belgie._pyproject import (
    PyprojectError,
    discover_pyproject_root,
    load_belgie_tool_config,
    parse_belgie_tool_config,
)


def write_pyproject(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


def test_parse_belgie_tool_config_defaults_source_to_project_root() -> None:
    config = parse_belgie_tool_config({})

    assert config.source == Path()


def test_parse_belgie_tool_config_reads_source() -> None:
    config = parse_belgie_tool_config(
        {
            "tool": {
                "belgie": {
                    "source": "src/mcp_app/views/widgets",
                },
            },
        },
    )

    assert config.source == Path("src/mcp_app/views/widgets")


@pytest.mark.parametrize(
    ("document", "match"),
    [
        pytest.param({"tool": {"belgie": {"source": ""}}}, "non-empty string", id="empty"),
        pytest.param({"tool": {"belgie": {"source": "/abs/widgets"}}}, "relative path", id="absolute"),
        pytest.param({"tool": {"belgie": {"source": "../widgets"}}}, "cannot contain", id="parent"),
        pytest.param({"tool": {"belgie": {"source": 1}}}, "must be a string", id="non-string"),
    ],
)
def test_parse_belgie_tool_config_rejects_invalid_source(document: dict[str, object], match: str) -> None:
    with pytest.raises(PyprojectError, match=match):
        parse_belgie_tool_config(document)


def test_load_belgie_tool_config_reads_project_file(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.belgie]
source = "widgets"
""",
    )

    config = load_belgie_tool_config(tmp_path)

    assert config.source == Path("widgets")


def test_discover_pyproject_root_walks_up_from_nested_directory(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[project]\nname = 'demo'\n")
    nested = tmp_path / "src" / "demo"
    nested.mkdir(parents=True)

    root = discover_pyproject_root(start=nested)

    assert root == tmp_path.resolve()


def test_discover_pyproject_root_reports_searched_paths(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "demo"
    nested.mkdir(parents=True)

    with pytest.raises(PyprojectError, match="Could not find pyproject.toml"):
        discover_pyproject_root(start=nested)
