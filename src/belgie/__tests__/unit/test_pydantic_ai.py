from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import AbstractToolset, RunContext, ToolDefinition
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.messages import ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.usage import RunUsage
from pydantic_core import SchemaValidator, core_schema

from belgie import Runtime, RuntimeOptions
from belgie.capabilities import pydantic_ai as pydantic_ai_capability
from belgie.capabilities.pydantic_ai import DEFAULT_RUN_CODE_INSTRUCTIONS, Belgie
from belgie.capabilities.pydantic_ai._toolset import RUN_CODE_METADATA, BelgieToolset


@pytest.fixture
def run_context() -> RunContext[None]:
    return RunContext[None](
        deps=None,
        model=TestModel(),
        usage=RunUsage(),
        prompt=None,
        messages=[],
        run_step=0,
        pending_messages=[],
    )


@pytest.fixture
def belgie_toolset() -> BelgieToolset[None]:
    toolset = Belgie[None]().get_wrapper_toolset(StaticToolset())
    assert isinstance(toolset, BelgieToolset)
    return toolset


class StaticToolset(AbstractToolset[None]):
    @property
    def id(self) -> str | None:
        return None

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:  # noqa: ARG002
        return {
            "external": ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name="external",
                    description="External tool that should not be exposed by Belgie.",
                    parameters_json_schema={"type": "object", "properties": {}},
                ),
                max_retries=1,
                args_validator=SchemaValidator(core_schema.any_schema()),
            ),
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],  # noqa: ARG002
        ctx: RunContext[None],  # noqa: ARG002
        tool: ToolsetTool[None],  # noqa: ARG002
    ) -> Any:
        return {"called": name}


def test_public_exports_are_limited() -> None:
    assert set(pydantic_ai_capability.__all__) == {"Belgie", "DEFAULT_RUN_CODE_INSTRUCTIONS"}
    assert Belgie.__name__ == "Belgie"
    assert DEFAULT_RUN_CODE_INSTRUCTIONS is pydantic_ai_capability.DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "JavaScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TypeScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "Deno" in DEFAULT_RUN_CODE_INSTRUCTIONS


def test_rejects_conflicting_configuration() -> None:
    with pytest.raises(UserError, match="mutually exclusive"):
        Belgie(instructions="append", dangerously_replace_instructions="replace")

    with pytest.raises(UserError, match="cannot be combined"):
        Belgie(runtime=Runtime(), runtime_options=RuntimeOptions())


async def test_tool_definition_exposes_typescript_run_code_only(
    run_context: RunContext[None],
    belgie_toolset: BelgieToolset[None],
) -> None:
    async with belgie_toolset:
        tools = await belgie_toolset.get_tools(run_context)

    assert list(tools) == ["run_code"]
    tool_def = tools["run_code"].tool_def
    assert tool_def.sequential is True
    assert tool_def.metadata == RUN_CODE_METADATA
    assert tool_def.parameters_json_schema["required"] == ["code"]


async def test_run_code_executes_typescript_script_module(
    run_context: RunContext[None],
    belgie_toolset: BelgieToolset[None],
) -> None:
    async with belgie_toolset:
        tools = await belgie_toolset.get_tools(run_context)
        result = await belgie_toolset.call_tool(
            "run_code",
            {
                "code": """
export default function run(): { total: number; label: string } {
  const values: number[] = [20, 22];
  return { total: values.reduce((sum, value) => sum + value, 0), label: "typescript" };
}
""",
            },
            run_context,
            tools["run_code"],
        )

    assert isinstance(result, ToolReturn)
    assert result.return_value == {"total": 42, "label": "typescript"}
    assert result.metadata == {"belgie": True, "code_language": RUN_CODE_METADATA["code_arg_language"]}


async def test_run_code_accepts_named_run_export(
    run_context: RunContext[None],
    belgie_toolset: BelgieToolset[None],
    named_run_source: str,
) -> None:
    async with belgie_toolset:
        tools = await belgie_toolset.get_tools(run_context)
        result = await belgie_toolset.call_tool(
            "run_code",
            {"code": named_run_source},
            run_context,
            tools["run_code"],
        )

    assert isinstance(result, ToolReturn)
    assert result.return_value == {"ok": True}


async def test_run_code_supports_multiple_calls_in_one_session(
    run_context: RunContext[None],
    belgie_toolset: BelgieToolset[None],
) -> None:
    async with belgie_toolset:
        tools = await belgie_toolset.get_tools(run_context)
        first = await belgie_toolset.call_tool(
            "run_code",
            {"code": "export default function run() { return { call: 1 }; }"},
            run_context,
            tools["run_code"],
        )
        second = await belgie_toolset.call_tool(
            "run_code",
            {"code": "export default function run() { return { call: 2 }; }"},
            run_context,
            tools["run_code"],
        )

    assert isinstance(first, ToolReturn)
    assert first.return_value == {"call": 1}
    assert isinstance(second, ToolReturn)
    assert second.return_value == {"call": 2}


async def test_script_errors_become_model_retries(
    run_context: RunContext[None],
    belgie_toolset: BelgieToolset[None],
) -> None:
    async with belgie_toolset:
        tools = await belgie_toolset.get_tools(run_context)
        with pytest.raises(ModelRetry, match="Belgie script execution failed"):
            await belgie_toolset.call_tool(
                "run_code",
                {"code": 'export default function run() { throw new Error("boom"); }'},
                run_context,
                tools["run_code"],
            )
