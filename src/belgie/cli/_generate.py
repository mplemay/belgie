from __future__ import annotations

import asyncio
import importlib
import os
import sys
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Final

from belgie import Runtime, Script
from belgie.cli._operations import create_environment
from belgie.cli._project import BelgieProject, ProjectError

if TYPE_CHECKING:
    from collections.abc import Iterator

MCP_DEPENDENCY: Final[str] = "@belgie/mcp"
MCP_REQUIRED_MESSAGE: Final[str] = 'belgie MCP dependencies are required. Install them with: uv add "belgie[mcp,cli]"'
GENERATE_SCRIPT: Final[str] = """
import { generateTypes } from "@belgie/mcp/generate";

export default async (tools) => await generateTypes(tools);
""".lstrip()


@dataclass(slots=True, kw_only=True, frozen=True)
class GenerateResult:
    path: Path
    tools: int
    changed: bool


def generate_tool_types(
    project: BelgieProject,
    *,
    target: str,
    output: Path,
    frozen: bool,
) -> GenerateResult:
    contracts = _load_tool_contracts(project, target)
    source = _compile_tool_contracts(project, contracts, frozen=frozen)
    path = output if output.is_absolute() else project.root / output
    resolved_path = path.resolve()
    changed = _write_if_changed(resolved_path, source)
    return GenerateResult(path=resolved_path, tools=len(contracts), changed=changed)


def _load_tool_contracts(project: BelgieProject, target: str) -> list[dict[str, Any]]:
    try:
        mcp_server_type = importlib.import_module("mcp.server").MCPServer
        belgie_extension_type = importlib.import_module("belgie.mcp").BelgieExtension
        generate_tool_types_context = importlib.import_module("belgie.mcp._extension").generate_tool_types_context
    except (AttributeError, ImportError) as exc:
        raise ProjectError(MCP_REQUIRED_MESSAGE) from exc

    module_name, separator, attribute_path = target.partition(":")
    if not separator or not module_name.strip() or not attribute_path.strip():
        msg = f"Invalid target {target!r}; expected module:attribute"
        raise ProjectError(msg)

    with generate_tool_types_context(), _project_import_context(project):
        try:
            imported = importlib.import_module(module_name)
            value: object = imported
            for segment in attribute_path.split("."):
                value = getattr(value, segment)
        except Exception as exc:
            msg = f"Could not import generation target {target!r}: {exc}"
            raise ProjectError(msg) from exc

    if isinstance(value, belgie_extension_type):
        server = mcp_server_type(name="belgie-type-generation", extensions=[value])
    elif isinstance(value, mcp_server_type):
        server = value
    else:
        msg = f"Generation target {target!r} must be a BelgieExtension or MCPServer, got {type(value).__name__}"
        raise ProjectError(msg)

    tools = asyncio.run(server.list_tools())
    if not tools:
        msg = f"Generation target {target!r} has no registered tools"
        raise ProjectError(msg)

    return [
        {
            "name": tool.name,
            "inputSchema": tool.input_schema,
            "outputSchema": tool.output_schema,
        }
        for tool in sorted(tools, key=lambda item: item.name)
    ]


@contextmanager
def _project_import_context(project: BelgieProject) -> Iterator[None]:
    previous_cwd = Path.cwd()
    candidates = [project.root / project.source, project.root]
    inserted: list[str] = []
    try:
        os.chdir(project.root)
        for candidate in reversed(candidates):
            value = str(candidate.resolve())
            if value not in sys.path:
                sys.path.insert(0, value)
                inserted.append(value)
        importlib.invalidate_caches()
        yield
    finally:
        os.chdir(previous_cwd)
        for value in inserted:
            with suppress(ValueError):
                sys.path.remove(value)


def _compile_tool_contracts(
    project: BelgieProject,
    contracts: list[dict[str, Any]],
    *,
    frozen: bool,
) -> str:
    if MCP_DEPENDENCY not in project.dependencies:
        msg = f"Missing {MCP_DEPENDENCY!r} in [tool.belgie.dependencies]"
        raise ProjectError(msg)

    with create_environment(project, frozen=frozen) as environment:
        environment.install()
        with Runtime(env=environment) as runtime:
            generated = runtime(Script(GENERATE_SCRIPT))(contracts)
    if not isinstance(generated, str):
        msg = f"{MCP_DEPENDENCY}/generate returned {type(generated).__name__}, expected str"
        raise ProjectError(msg)
    return generated


def _write_if_changed(path: Path, source: str) -> bool:
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == source:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(source)
            temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(path)
        except OSError:
            temporary_path.unlink(missing_ok=True)
            raise
    except OSError as exc:
        msg = f"Could not write generated types to {path}: {exc}"
        raise ProjectError(msg) from exc
    return True
