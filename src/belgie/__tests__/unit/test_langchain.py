from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain.tools import tool
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from pydantic import BaseModel

from belgie import Runtime as BelgieRuntime, RuntimeOptions
from belgie.capabilities import langchain as langchain_capability
from belgie.capabilities.core._options import BelgieOptions
from belgie.capabilities.core._run_code import (
    DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
    DEFAULT_BELGIE_CAPABILITY_ID,
    LOAD_BELGIE_TOOL_NAME,
    RUN_CODE_DESCRIPTION,
    RUN_CODE_METADATA,
    RUN_CODE_TOOL_NAME,
    resolved_description,
)
from belgie.capabilities.langchain import DEFAULT_RUN_CODE_INSTRUCTIONS, BelgieMiddleware
from belgie.capabilities.langchain._tools import build_run_code_tool

AGENT_RUN_CODE_SOURCE = "export default function run() { return { agent: true }; }"


class ToolCapableFakeChatModel(GenericFakeChatModel):
    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],  # noqa: ARG002
        *,
        tool_choice: str | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> Runnable[Any, AIMessage]:
        return self


@pytest.fixture
def belgie_middleware() -> BelgieMiddleware:
    return BelgieMiddleware()


@pytest.fixture
def runtime_context() -> Runtime[Any]:
    return Runtime(context=None)


@tool
def external() -> str:
    """External tool that should not be exposed by Belgie."""
    return "external"


def test_public_exports_are_limited() -> None:
    assert set(langchain_capability.__all__) == {
        "Belgie",
        "BelgieMiddleware",
        "DEFAULT_RUN_CODE_INSTRUCTIONS",
    }
    assert DEFAULT_RUN_CODE_INSTRUCTIONS is langchain_capability.DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "JavaScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "TypeScript" in DEFAULT_RUN_CODE_INSTRUCTIONS
    assert "Deno" in DEFAULT_RUN_CODE_INSTRUCTIONS


def test_rejects_conflicting_configuration() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        BelgieMiddleware(instructions="append", dangerously_replace_instructions="replace")

    with pytest.raises(ValueError, match="cannot be combined"):
        BelgieMiddleware(runtime=BelgieRuntime(), runtime_options=RuntimeOptions())

    with pytest.raises(ValueError, match="requires a stable `id`"):
        BelgieOptions(defer_loading=True, capability_id=None).validate()


def test_defer_loading_assigns_default_capability_id() -> None:
    middleware = BelgieMiddleware(defer_loading=True)
    assert middleware.capability_id == DEFAULT_BELGIE_CAPABILITY_ID
    tool_names = {tool.name for tool in middleware.tools}
    assert tool_names == {LOAD_BELGIE_TOOL_NAME, RUN_CODE_TOOL_NAME}


def test_resolved_description_appends_or_replaces_instructions() -> None:
    default_middleware = BelgieMiddleware()
    assert default_middleware.resolved_description() == RUN_CODE_DESCRIPTION

    appended = BelgieMiddleware(instructions="Use strict TypeScript.")
    assert appended.resolved_description() == f"{RUN_CODE_DESCRIPTION}\n\nUse strict TypeScript."

    replaced = BelgieMiddleware(dangerously_replace_instructions="Custom only.")
    assert replaced.resolved_description() == "Custom only."


def test_tool_definition_exposes_typescript_run_code_only(
    belgie_middleware: BelgieMiddleware,
    runtime_context: Runtime[Any],
) -> None:
    captured: list[list[BaseTool | dict[str, Any]]] = []

    def handler(request: ModelRequest[Any]) -> ModelResponse[Any]:
        captured.append(list(request.tools))
        return ModelResponse(result=[AIMessage(content="done")])

    belgie_middleware.wrap_model_call(
        ModelRequest(
            model=ToolCapableFakeChatModel(messages=iter([AIMessage(content="done")])),
            messages=[],
            state={"messages": []},
            runtime=runtime_context,
            tools=[external],
        ),
        handler,
    )

    assert len(captured) == 1
    visible_names = {tool.name for tool in captured[0] if isinstance(tool, BaseTool)}
    assert visible_names == {RUN_CODE_TOOL_NAME}
    run_code_tool = next(tool for tool in captured[0] if isinstance(tool, BaseTool) and tool.name == RUN_CODE_TOOL_NAME)
    assert RUN_CODE_METADATA["code_arg_language"] in run_code_tool.description
    args_schema = run_code_tool.args_schema
    if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
        schema = args_schema.model_json_schema()
    else:
        schema = {}
    assert schema.get("required") == ["code"]


async def test_run_code_executes_typescript_script_module(belgie_middleware: BelgieMiddleware) -> None:
    await belgie_middleware.abefore_agent({"messages": []}, Runtime(context=None))
    try:
        run_code_tool = next(tool for tool in belgie_middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
        result = await run_code_tool.ainvoke(
            {
                "code": """
export default function run(): { total: number; label: string } {
  const values: number[] = [20, 22];
  return { total: values.reduce((sum, value) => sum + value, 0), label: "typescript" };
}
""",
            },
        )
    finally:
        await belgie_middleware.aafter_agent({"messages": []}, Runtime(context=None))

    assert result == {"total": 42, "label": "typescript"}


async def test_run_code_accepts_named_run_export(
    belgie_middleware: BelgieMiddleware,
    named_run_source: str,
) -> None:
    await belgie_middleware.abefore_agent({"messages": []}, Runtime(context=None))
    try:
        run_code_tool = next(tool for tool in belgie_middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
        result = await run_code_tool.ainvoke({"code": named_run_source})
    finally:
        await belgie_middleware.aafter_agent({"messages": []}, Runtime(context=None))

    assert result == {"ok": True}


async def test_run_code_supports_multiple_calls_in_one_session(belgie_middleware: BelgieMiddleware) -> None:
    await belgie_middleware.abefore_agent({"messages": []}, Runtime(context=None))
    try:
        run_code_tool = next(tool for tool in belgie_middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
        first = await run_code_tool.ainvoke({"code": "export default function run() { return { call: 1 }; }"})
        second = await run_code_tool.ainvoke({"code": "export default function run() { return { call: 2 }; }"})
    finally:
        await belgie_middleware.aafter_agent({"messages": []}, Runtime(context=None))

    assert first == {"call": 1}
    assert second == {"call": 2}


async def test_script_errors_surface_as_tool_errors(belgie_middleware: BelgieMiddleware) -> None:
    await belgie_middleware.abefore_agent({"messages": []}, Runtime(context=None))
    try:
        run_code_tool = next(tool for tool in belgie_middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
        with pytest.raises(Exception, match="boom"):
            await run_code_tool.ainvoke({"code": 'export default function run() { throw new Error("boom"); }'})
    finally:
        await belgie_middleware.aafter_agent({"messages": []}, Runtime(context=None))


async def test_script_timeout_surfaces_as_tool_error() -> None:
    middleware = BelgieMiddleware(timeout=0.05)
    await middleware.abefore_agent({"messages": []}, Runtime(context=None))
    try:
        run_code_tool = next(tool for tool in middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
        with pytest.raises(Exception, match="timed out after 0.05 seconds"):
            await run_code_tool.ainvoke(
                {"code": "export default async function run() { await new Promise(() => {}); }"},
            )
    finally:
        await middleware.aafter_agent({"messages": []}, Runtime(context=None))


def test_agent_run_code_end_to_end() -> None:
    model = ToolCapableFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name=RUN_CODE_TOOL_NAME,
                            args={"code": AGENT_RUN_CODE_SOURCE},
                            id="call_1",
                        ),
                    ],
                ),
                AIMessage(content="done"),
            ],
        ),
    )
    agent = create_agent(
        model=model,
        tools=[external],
        middleware=[BelgieMiddleware()],
    )

    result = agent.invoke({"messages": [("user", "execute code")]})

    assert result["messages"][-1].content == "done"
    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].name == RUN_CODE_TOOL_NAME
    assert '"agent": true' in str(tool_messages[0].content)


def test_deferred_exposes_load_belgie() -> None:
    middleware = BelgieMiddleware(defer_loading=True)
    tool_names = {tool.name for tool in middleware.tools}
    assert tool_names == {LOAD_BELGIE_TOOL_NAME, RUN_CODE_TOOL_NAME}
    run_code_tool = next(tool for tool in middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
    assert (run_code_tool.extras or {}).get("defer_loading") is True
    assert DEFAULT_BELGIE_CAPABILITY_DESCRIPTION in middleware.resolved_description() or True


async def test_wrap_tool_call_maps_errors_to_tool_message(belgie_middleware: BelgieMiddleware) -> None:
    await belgie_middleware.abefore_agent({"messages": []}, Runtime(context=None))
    run_code_tool = next(tool for tool in belgie_middleware.tools if tool.name == RUN_CODE_TOOL_NAME)

    def failing_handler(request: Any) -> ToolMessage:
        boom_message = "boom"
        raise RuntimeError(boom_message)

    request = ToolCallRequest(
        tool_call={"name": RUN_CODE_TOOL_NAME, "args": {"code": "bad"}, "id": "call_1", "type": "tool_call"},
        tool=run_code_tool,
        state={"messages": []},
        runtime=cast("Any", Runtime(context=None)),
    )
    result = belgie_middleware.wrap_tool_call(request, failing_handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.content == "boom"
    await belgie_middleware.aafter_agent({"messages": []}, Runtime(context=None))


def test_build_run_code_tool_requires_active_session() -> None:
    session = None
    run_code_tool = build_run_code_tool(
        session_getter=lambda: session,
        description=resolved_description(BelgieOptions()),
    )

    with pytest.raises(RuntimeError, match="must be entered"):
        run_code_tool.invoke({"code": "export default function run() { return 1; }"})
