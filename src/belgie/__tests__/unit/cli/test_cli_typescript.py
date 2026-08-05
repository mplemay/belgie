from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from belgie.cli import _typescript
from belgie.cli.__main__ import app
from belgie.cli._project import ProjectError, load_project
from belgie.cli._typescript import TypeScriptResult, _load_tool_contracts, _write_if_changed, generate_typescript

runner = CliRunner()


def write_project(root: Path, *, dependency: bool = True) -> None:
    dependency_entry = (
        '"@belgie/mcp" = "file:packages/mcp"' if dependency else ""
    )
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "demo"

[tool.belgie]
source = "src"

[tool.belgie.typescript]
target = "generation_target:server"
output = "generated/tools.ts"

[tool.belgie.dependencies]
{dependency_entry}
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


server = MCPServer(name="demo", extensions=[extension])
wrong = 42
empty = BelgieExtension(project=Path.cwd())
""".lstrip(),
        encoding="utf-8",
    )


@pytest.fixture
def target_project(tmp_path: Path):
    module_name = "generation_target"
    write_project(tmp_path)
    write_target_module(tmp_path, module_name)
    yield load_project(tmp_path), module_name
    sys.modules.pop(module_name, None)


@pytest.mark.parametrize("attribute", ["extension", "server"])
def test_load_tool_contracts_is_schema_only(target_project, attribute: str) -> None:
    project, module_name = target_project

    contracts = _load_tool_contracts(project, f"{module_name}:{attribute}")

    assert [contract["name"] for contract in contracts] == ["typed"]
    assert contracts[0]["inputSchema"]["properties"]["count"]["default"] == 1
    assert contracts[0]["outputSchema"]["title"] == "Payload"
    assert not importlib.import_module(module_name).CALLED


@pytest.mark.parametrize(
    ("target", "match"),
    [
        ("invalid", "expected module:attribute"),
        ("{module}:missing", "Could not import TypeScript target"),
        ("{module}:wrong", "must be a BelgieExtension or MCPServer"),
        ("{module}:empty", "has no registered tools"),
    ],
)
def test_load_tool_contracts_reports_invalid_targets(target_project, target: str, match: str) -> None:
    project, module_name = target_project

    with pytest.raises(ProjectError, match=match):
        _load_tool_contracts(project, target.format(module=module_name))


def test_compile_tool_contracts_requires_mcp_dependency(tmp_path: Path) -> None:
    write_project(tmp_path, dependency=False)

    with pytest.raises(ProjectError, match="@belgie/mcp"):
        _typescript._compile_tool_contracts(load_project(tmp_path), [], frozen=True)


def test_write_if_changed_is_atomic_and_preserves_unchanged_file(tmp_path: Path) -> None:
    path = tmp_path / "generated" / "tools.ts"

    assert _write_if_changed(path, "export type Value = string;\n")
    initial = path.stat()
    assert not _write_if_changed(path, "export type Value = string;\n")
    assert path.stat().st_ino == initial.st_ino
    assert path.stat().st_mtime_ns == initial.st_mtime_ns


def test_typescript_check_rejects_stale_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_project(tmp_path)
    project = load_project(tmp_path)
    output = tmp_path / "generated" / "tools.ts"
    output.parent.mkdir()
    output.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(_typescript, "_load_tool_contracts", lambda project, target: [{"name": "typed"}])
    monkeypatch.setattr(_typescript, "_compile_tool_contracts", lambda project, contracts, frozen: "new\n")

    with pytest.raises(ProjectError, match="stale or missing"):
        generate_typescript(project, target=None, output=None, frozen=True, check=True)

    assert output.read_text(encoding="utf-8") == "old\n"


def test_generate_command_uses_configured_target_and_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_project(tmp_path)
    received: list[tuple[str | None, Path | None, bool, bool]] = []

    def fake_generate(
        project: object,
        *,
        target: str | None,
        output: Path | None,
        frozen: bool,
        check: bool,
    ) -> TypeScriptResult:
        received.append((target, output, frozen, check))
        return TypeScriptResult(path=tmp_path / "generated" / "tools.ts", tools=1, changed=True)

    monkeypatch.setattr("belgie.cli.__main__.generate_typescript", fake_generate)

    generate_result = runner.invoke(app, ["generate", "-C", str(tmp_path)])
    override_result = runner.invoke(
        app,
        [
            "generate",
            "override:server",
            "-o",
            "override.ts",
            "-C",
            str(tmp_path),
        ],
    )

    assert generate_result.exit_code == 0, generate_result.output
    assert override_result.exit_code == 0, override_result.output
    assert received == [
        (None, None, True, False),
        ("override:server", Path("override.ts"), True, False),
    ]


def test_typescript_command_requires_configured_values(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")

    result = runner.invoke(app, ["generate", "-C", str(tmp_path)])

    assert result.exit_code == 1
    assert isinstance(result.exception, ProjectError)
    assert "No TypeScript target configured" in str(result.exception)
