from __future__ import annotations

from typing import Any, Final

import pytest
from pydantic_ai import AbstractToolset, Agent, ModelResponse, RunContext, ToolDefinition
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.messages import ModelRequest, TextPart, ToolCallPart, ToolReturn
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets._deferred_capability_loader import LOAD_CAPABILITY_TOOL_NAME
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.usage import RunUsage
from pydantic_core import SchemaValidator, core_schema

from belgie import Runtime, RuntimeOptions, pydantic_ai as pydantic_ai_capability
from belgie.agent import RUN_CODE_METADATA, RUN_CODE_TOOL_NAME
from belgie.agent._run_code import (
    DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
    DEFAULT_BELGIE_CAPABILITY_ID,
    RUN_CODE_DESCRIPTION,
    resolved_description,
)
from belgie.pydantic_ai import DEFAULT_RUN_CODE_INSTRUCTIONS, BelgieCapability
from belgie.pydantic_ai._toolset import BelgieToolset

AGENT_RUN_CODE_SOURCE: Final[str] = "export default function run() { return { agent: true }; }"


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
    toolset = BelgieCapability[None]().get_wrapper_toolset(StaticToolset())
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
    assert set(pydantic_ai_capability.__all__) == {"BelgieCapability", "DEFAULT_RUN_CODE_INSTRUCTIONS"}
    assert BelgieCapability.__name__ == "BelgieCapability"
    assert DEFAULT_RUN_CODE_INSTRUCTIONS is pydantic_ai_capability.DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "JavaScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TypeScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TSX" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "Deno" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "npm:@belgie/render" in DEFAULT_RUN_CODE_INSTRUCTIONS


def test_rejects_conflicting_configuration() -> None:
    with pytest.raises(UserError, match="mutually exclusive"):
        BelgieCapability(instructions="append", dangerously_replace_instructions="replace")

    with pytest.raises(UserError, match="cannot be combined"):
        BelgieCapability(runtime=Runtime(), runtime_options=RuntimeOptions())

    with pytest.raises(UserError, match="requires a stable `id`"):
        BelgieToolset(wrapped=StaticToolset(), defer_loading=True, capability_id=None)


def test_defer_loading_assigns_default_id_and_description() -> None:
    belgie = BelgieCapability(defer_loading=True)
    assert belgie.id == DEFAULT_BELGIE_CAPABILITY_ID
    assert belgie.description == DEFAULT_BELGIE_CAPABILITY_DESCRIPTION
    assert belgie.capability_id == DEFAULT_BELGIE_CAPABILITY_ID


def test_resolved_description_appends_or_replaces_instructions(belgie_toolset: BelgieToolset[None]) -> None:
    default_toolset = BelgieToolset(wrapped=StaticToolset())
    assert resolved_description(default_toolset) == RUN_CODE_DESCRIPTION

    appended = BelgieToolset(wrapped=StaticToolset(), instructions="Use strict TypeScript.")
    assert resolved_description(appended) == f"{RUN_CODE_DESCRIPTION}\n\nUse strict TypeScript."

    replaced = BelgieToolset(wrapped=StaticToolset(), dangerously_replace_instructions="Custom only.")
    assert resolved_description(replaced) == "Custom only."


async def test_deferred_capability_marks_run_code(run_context: RunContext[None]) -> None:
    toolset = BelgieToolset(
        wrapped=StaticToolset(),
        defer_loading=True,
        capability_id=DEFAULT_BELGIE_CAPABILITY_ID,
    )

    async with toolset:
        tools = await toolset.get_tools(run_context)

    assert list(tools) == [RUN_CODE_TOOL_NAME]
    assert tools[RUN_CODE_TOOL_NAME].tool_def.defer_loading is True
    assert tools[RUN_CODE_TOOL_NAME].tool_def.capability_id == DEFAULT_BELGIE_CAPABILITY_ID


async def test_deferred_agent_exposes_load_capability() -> None:
    agent = Agent("test", capabilities=[BelgieCapability(defer_loading=True)])
    model = TestModel(call_tools=[], custom_output_text="done")

    with agent.override(model=model):
        await agent.run("test")

    assert model.last_model_request_parameters is not None
    tool_names = {tool.name for tool in model.last_model_request_parameters.function_tools}
    assert tool_names == {LOAD_CAPABILITY_TOOL_NAME, RUN_CODE_TOOL_NAME}
    run_code = next(
        tool for tool in model.last_model_request_parameters.function_tools if tool.name == RUN_CODE_TOOL_NAME
    )
    assert run_code.defer_loading is True


async def test_agent_run_code_through_capability_wiring() -> None:
    agent = Agent("test", capabilities=[BelgieCapability()])
    model_steps: list[list[str]] = []

    def belgie_model(messages: list[Any], info: Any) -> ModelResponse:
        model_steps.append([tool.name for tool in info.function_tools])
        has_run_code_return = any(
            isinstance(message, ModelRequest)
            and any(getattr(part, "tool_name", None) == RUN_CODE_TOOL_NAME for part in message.parts)
            for message in messages
        )
        if has_run_code_return:
            return ModelResponse(parts=[TextPart(content="done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=RUN_CODE_TOOL_NAME,
                    args={"code": AGENT_RUN_CODE_SOURCE},
                    tool_call_id="call_1",
                ),
            ],
        )

    with agent.override(model=FunctionModel(belgie_model)):
        result = await agent.run("execute code")

    assert result.output == "done"
    assert RUN_CODE_TOOL_NAME in model_steps[0]


async def test_script_timeout_becomes_model_retry(
    run_context: RunContext[None],
) -> None:
    toolset = BelgieToolset(wrapped=StaticToolset(), timeout=0.05)
    async with toolset:
        tools = await toolset.get_tools(run_context)
        with pytest.raises(ModelRetry, match="timed out after 0.05 seconds"):
            await toolset.call_tool(
                RUN_CODE_TOOL_NAME,
                {"code": "export default async function run() { await new Promise(() => {}); }"},
                run_context,
                tools[RUN_CODE_TOOL_NAME],
            )


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
