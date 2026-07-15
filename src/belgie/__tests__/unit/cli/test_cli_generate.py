from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from belgie.cli import _generate
from belgie.cli._generate import _load_tool_contracts, _write_if_changed
from belgie.cli._project import ProjectError, load_project


def write_project(root: Path, *, source: str = "src", dependency: bool = True) -> None:
    dependencies = '\n"@belgie/mcp" = "file:package"' if dependency else ""
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "demo"

[tool.belgie]
source = "{source}"

[tool.belgie.dependencies]
{dependencies}
""",
        encoding="utf-8",
    )


def write_target_module(root: Path, module_name: str) -> None:
    source = root / "src"
    source.mkdir()
    (source / f"{module_name}.py").write_text(
        """
from pathlib import Path

from mcp.server import MCPServer
from pydantic import BaseModel

from belgie.mcp import BelgieExtension


class Payload(BaseModel):
    value: str


CALLED = False
extension = BelgieExtension(project=Path.cwd())


@extension.tool(widget=Path("missing/widget.tsx"), name="typed")
def typed(payload: Payload, count: int = 1) -> Payload:
    global CALLED
    CALLED = True
    return payload


@extension.tool(widget=Path("missing/widget.tsx"), name="raw", structured_output=False)
def raw() -> str:
    global CALLED
    CALLED = True
    return "raw"


server = MCPServer(name="demo", extensions=[extension])
wrong = 42
empty = BelgieExtension(project=Path.cwd())
""".lstrip(),
        encoding="utf-8",
    )


@pytest.fixture
def target_project(tmp_path: Path):
    module_name = f"generation_{tmp_path.name.replace('-', '_')}"
    write_project(tmp_path)
    write_target_module(tmp_path, module_name)
    yield load_project(tmp_path), module_name
    sys.modules.pop(module_name, None)


@pytest.mark.parametrize("attribute", ["extension", "server"])
def test_load_tool_contracts_reads_registered_schemas_without_calling_tools(
    target_project,
    attribute: str,
) -> None:
    project, module_name = target_project

    contracts = _load_tool_contracts(project, f"{module_name}:{attribute}")

    assert [contract["name"] for contract in contracts] == ["raw", "typed"]
    assert contracts[0]["outputSchema"] is None
    assert contracts[1]["inputSchema"]["properties"]["count"]["default"] == 1
    assert "Payload" in contracts[1]["inputSchema"]["$defs"]
    assert contracts[1]["outputSchema"]["title"] == "Payload"
    assert not importlib.import_module(module_name).CALLED


@pytest.mark.parametrize(
    ("target", "match"),
    [
        ("invalid", "expected module:attribute"),
        ("{module}:missing", "Could not import generation target"),
        ("{module}:wrong", "must be a BelgieExtension or MCPServer"),
        ("{module}:empty", "has no registered tools"),
    ],
)
def test_load_tool_contracts_reports_invalid_targets(
    target_project,
    target: str,
    match: str,
) -> None:
    project, module_name = target_project

    with pytest.raises(ProjectError, match=match):
        _load_tool_contracts(project, target.format(module=module_name))


def test_compile_tool_contracts_requires_mcp_javascript_dependency(tmp_path: Path) -> None:
    write_project(tmp_path, dependency=False)

    with pytest.raises(ProjectError, match="@belgie/mcp"):
        _generate._compile_tool_contracts(load_project(tmp_path), [], frozen=True)


def test_write_if_changed_is_atomic_and_preserves_unchanged_file(tmp_path: Path) -> None:
    path = tmp_path / "generated" / "tools.ts"

    assert _write_if_changed(path, "export interface Tools {}\n")
    initial = path.stat()
    assert not _write_if_changed(path, "export interface Tools {}\n")

    assert path.stat().st_ino == initial.st_ino
    assert path.stat().st_mtime_ns == initial.st_mtime_ns
    assert _write_if_changed(path, "export interface Tools { changed: true }\n")
    assert path.read_text(encoding="utf-8") == "export interface Tools { changed: true }\n"


def test_write_if_changed_reports_output_failure(tmp_path: Path) -> None:
    parent = tmp_path / "not-a-directory"
    parent.write_text("file", encoding="utf-8")

    with pytest.raises(ProjectError, match="Could not write generated types"):
        _write_if_changed(parent / "tools.ts", "types")
