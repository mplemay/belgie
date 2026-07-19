from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal, NotRequired, TypedDict
from uuid import UUID

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.utilities.types import Audio, Image
from mcp_types import CallToolResult, ContentBlock
from pydantic import AnyUrl, BaseModel, Field, JsonValue

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[5]
PYTHON_MCP_V2_FIXTURE: Final[Path] = (
    PROJECT_ROOT / "packages" / "mcp" / "tests" / "fixtures" / "python-mcp-v2-tools.json"
)

pytestmark = pytest.mark.integration


class Color(StrEnum):
    RED = "red"
    BLUE = "blue"


class Payload(TypedDict):
    name: str
    count: NotRequired[int]


@dataclass(kw_only=True)
class Point:
    x: float
    y: float


class AnnotatedPoint:
    x: float
    y: float


class Node(BaseModel):
    name: str
    child: Node | None = None


class Cat(BaseModel):
    kind: Literal["cat"]
    lives: int


class Dog(BaseModel):
    kind: Literal["dog"]
    good: bool


class Zoo(BaseModel):
    pet: Annotated[Cat | Dog, Field(discriminator="kind")]


class StandardValues(BaseModel):
    when: datetime
    day: date
    clock: time
    delta: timedelta
    amount: Decimal
    uid: UUID
    path: Path
    url: AnyUrl


class CommonOutput(BaseModel):
    payload: Payload
    point: Point
    node: Node
    zoo: Zoo
    standard: StandardValues


def common_inputs(
    *,
    required: str,
    count: int,
    ratio: float | None,
    enabled: bool,
    raw: bytes,
    items: list[str],
    tags: set[str],
    frozen: frozenset[int],
    pair: tuple[str, int],
    variable: tuple[int, ...],
    mapping: dict[str, int],
    anything: dict[str, Any],
    choice: Literal["a", "b"],
    color: Color,
    constrained: Annotated[int, Field(ge=1, le=10)],
    payload: Payload,
    point: Point,
    node: Node,
    zoo: Zoo,
    json_value: JsonValue,
    when: datetime,
    day: date,
    clock: time,
    delta: timedelta,
    amount: Decimal,
    uid: UUID,
    path: Path,
    url: AnyUrl,
    optional: str | None = None,
    limit: int = 10,
) -> CommonOutput:
    raise NotImplementedError


def primitive_output() -> str:
    raise NotImplementedError


def generic_output() -> list[str]:
    raise NotImplementedError


def dictionary_output() -> dict[str, int]:
    raise NotImplementedError


def typed_dict_output() -> Payload:
    raise NotImplementedError


def dataclass_output() -> Point:
    raise NotImplementedError


def annotated_class_output() -> AnnotatedPoint:
    raise NotImplementedError


def content_blocks() -> list[ContentBlock]:
    raise NotImplementedError


def image_helper() -> Image:
    raise NotImplementedError


def audio_helper() -> Audio:
    raise NotImplementedError


def direct_result() -> CallToolResult:
    raise NotImplementedError


def any_output() -> Any:
    raise NotImplementedError


def disabled_output() -> str:
    raise NotImplementedError


def python_mcp_v2_server() -> MCPServer:
    server = MCPServer("Python MCP v2 codegen fixture")
    server.tool(name="common-inputs")(common_inputs)
    server.tool(name="primitive-output")(primitive_output)
    server.tool(name="generic-output")(generic_output)
    server.tool(name="dictionary-output")(dictionary_output)
    server.tool(name="typed-dict-output")(typed_dict_output)
    server.tool(name="dataclass-output")(dataclass_output)
    server.tool(name="annotated-class-output")(annotated_class_output)
    server.tool(name="content-blocks")(content_blocks)
    server.tool(name="image-helper")(image_helper)
    server.tool(name="audio-helper")(audio_helper)
    server.tool(name="direct-result")(direct_result)
    server.tool(name="any-output")(any_output)
    server.tool(name="disabled-output", structured_output=False)(disabled_output)
    return server


async def python_mcp_v2_tool_schemas() -> list[dict[str, Any]]:
    tools = await python_mcp_v2_server().list_tools()
    return [
        {
            "name": tool.name,
            "inputSchema": tool.input_schema,
            **({"outputSchema": tool.output_schema} if tool.output_schema is not None else {}),
        }
        for tool in sorted(tools, key=lambda tool: tool.name)
    ]


async def test_python_mcp_v2_schema_fixture_matches_public_tool_listing() -> None:
    expected = json.loads(PYTHON_MCP_V2_FIXTURE.read_text(encoding="utf-8"))
    assert await python_mcp_v2_tool_schemas() == expected
