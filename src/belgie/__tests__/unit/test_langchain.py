from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain.tools import ToolRuntime, tool
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolCall, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime

from belgie import Runtime as BelgieRuntime, RuntimeOptions, langchain as langchain_capability
from belgie.agent._options import BelgieOptions
from belgie.agent._run_code import (
    DEFAULT_BELGIE_CAPABILITY_ID,
    LOAD_BELGIE_TOOL_NAME,
    RUN_CODE_DESCRIPTION,
    RUN_CODE_JSON_SCHEMA,
    RUN_CODE_METADATA,
    RUN_CODE_TOOL_NAME,
    resolved_description,
)
from belgie.langchain import DEFAULT_RUN_CODE_INSTRUCTIONS, BelgieMiddleware
from belgie.langchain._tools import build_run_code_tool

if TYPE_CHECKING:
    from belgie.langchain._state import BelgieAgentState

AGENT_RUN_CODE_SOURCE: Final[str] = "export default function run() { return { agent: true }; }"


def tool_runtime(state: BelgieAgentState, *, tool_call_id: str = "call_1") -> ToolRuntime[Any, BelgieAgentState]:
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id=tool_call_id,
        store=None,
    )


@asynccontextmanager
async def active_langchain_state(middleware: BelgieMiddleware) -> AsyncIterator[BelgieAgentState]:
    state: BelgieAgentState = {"messages": []}
    update = await middleware.abefore_agent(state, Runtime(context=None))
    if update:
        state.update(cast("BelgieAgentState", update))
    try:
        yield state
    finally:
        await middleware.aafter_agent(state, Runtime(context=None))


class ToolCapableFakeChatModel(GenericFakeChatModel):
    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],  # noqa: ARG002
        *,
        tool_choice: str | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> Runnable[Any, AIMessage]:
        return self


class SessionRoutingFakeChatModel(ToolCapableFakeChatModel):
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        if any(isinstance(message, ToolMessage) for message in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

        label = str(messages[-1].content)
        code = f"""
export default function run() {{
  globalThis.labels = globalThis.labels ?? [];
  globalThis.labels.push({json.dumps(label)});
  return {{ labels: globalThis.labels }};
}}
"""
        message = AIMessage(
            content="",
            tool_calls=[
                ToolCall(
                    name=RUN_CODE_TOOL_NAME,
                    args={"code": code},
                    id=f"call_{label}",
                ),
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.fixture
def belgie_middleware() -> BelgieMiddleware:
    return BelgieMiddleware()


@pytest.fixture
def run_code_tool(belgie_middleware: BelgieMiddleware) -> BaseTool:
    return next(tool for tool in belgie_middleware.tools if tool.name == RUN_CODE_TOOL_NAME)


@pytest.fixture
def runtime_context() -> Runtime[Any]:
    return Runtime(context=None)


@tool
def external() -> str:
    """External tool that should not be exposed by Belgie."""
    return "external"


def test_public_exports_are_limited() -> None:
    assert set(langchain_capability.__all__) == {
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
    assert resolved_description(default_middleware) == RUN_CODE_DESCRIPTION

    appended = BelgieMiddleware(instructions="Use strict TypeScript.")
    assert resolved_description(appended) == f"{RUN_CODE_DESCRIPTION}\n\nUse strict TypeScript."

    replaced = BelgieMiddleware(dangerously_replace_instructions="Custom only.")
    assert resolved_description(replaced) == "Custom only."


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
    assert RUN_CODE_JSON_SCHEMA["required"] == ["code"]


async def test_run_code_executes_typescript_script_module(
    belgie_middleware: BelgieMiddleware,
    run_code_tool: BaseTool,
) -> None:
    async with active_langchain_state(belgie_middleware) as state:
        result = await run_code_tool.ainvoke(
            {
                "code": """
export default function run(): { total: number; label: string } {
  const values: number[] = [20, 22];
  return { total: values.reduce((sum, value) => sum + value, 0), label: "typescript" };
}
""",
                "runtime": tool_runtime(state),
            },
        )

    assert result == {"total": 42, "label": "typescript"}


async def test_run_code_accepts_named_run_export(
    belgie_middleware: BelgieMiddleware,
    run_code_tool: BaseTool,
    named_run_source: str,
) -> None:
    async with active_langchain_state(belgie_middleware) as state:
        result = await run_code_tool.ainvoke({"code": named_run_source, "runtime": tool_runtime(state)})

    assert result == {"ok": True}


async def test_run_code_supports_multiple_calls_in_one_session(
    belgie_middleware: BelgieMiddleware,
    run_code_tool: BaseTool,
) -> None:
    async with active_langchain_state(belgie_middleware) as state:
        first = await run_code_tool.ainvoke(
            {"code": "export default function run() { return { call: 1 }; }", "runtime": tool_runtime(state)},
        )
        second = await run_code_tool.ainvoke(
            {"code": "export default function run() { return { call: 2 }; }", "runtime": tool_runtime(state)},
        )

    assert first == {"call": 1}
    assert second == {"call": 2}


async def test_script_errors_surface_as_tool_errors(
    belgie_middleware: BelgieMiddleware,
    run_code_tool: BaseTool,
) -> None:
    async with active_langchain_state(belgie_middleware) as state:
        with pytest.raises(Exception, match="boom"):
            await run_code_tool.ainvoke(
                {
                    "code": 'export default function run() { throw new Error("boom"); }',
                    "runtime": tool_runtime(state),
                },
            )


async def test_script_timeout_surfaces_as_tool_error() -> None:
    middleware = BelgieMiddleware(timeout=0.05)
    async with active_langchain_state(middleware) as state:
        run_code_tool = next(tool for tool in middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
        with pytest.raises(Exception, match="timed out after 0.05 seconds"):
            await run_code_tool.ainvoke(
                {
                    "code": "export default async function run() { await new Promise(() => {}); }",
                    "runtime": tool_runtime(state),
                },
            )


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


async def test_agent_abatch_scopes_runtime_sessions_per_invocation() -> None:
    agent = create_agent(
        model=SessionRoutingFakeChatModel(messages=iter([])),
        tools=[external],
        middleware=[BelgieMiddleware()],
    )

    results = await agent.abatch(
        [
            {"messages": [("user", "alpha")]},
            {"messages": [("user", "beta")]},
        ],
    )

    for result, label, other_label in zip(results, ("alpha", "beta"), ("beta", "alpha"), strict=True):
        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        assert len(tool_messages) == 1
        content = str(tool_messages[0].content)
        assert json.dumps(label) in content
        assert json.dumps(other_label) not in content


def test_deferred_exposes_load_belgie() -> None:
    middleware = BelgieMiddleware(defer_loading=True)
    tool_names = {tool.name for tool in middleware.tools}
    assert tool_names == {LOAD_BELGIE_TOOL_NAME, RUN_CODE_TOOL_NAME}
    run_code_tool = next(tool for tool in middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
    assert (run_code_tool.extras or {}).get("defer_loading") is True


async def test_wrap_tool_call_maps_errors_to_tool_message(
    belgie_middleware: BelgieMiddleware,
    run_code_tool: BaseTool,
) -> None:
    async with active_langchain_state(belgie_middleware) as state:

        def failing_handler(request: Any) -> ToolMessage:
            boom_message = "boom"
            raise RuntimeError(boom_message)

        request = ToolCallRequest(
            tool_call={"name": RUN_CODE_TOOL_NAME, "args": {"code": "bad"}, "id": "call_1", "type": "tool_call"},
            tool=run_code_tool,
            state=state,
            runtime=cast("Any", tool_runtime(state)),
        )
        result = belgie_middleware.wrap_tool_call(request, failing_handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.content == "boom"


def test_build_run_code_tool_requires_active_session() -> None:
    run_code_tool = build_run_code_tool(description=resolved_description(BelgieOptions()))

    with pytest.raises(RuntimeError, match="must be entered"):
        run_code_tool.invoke(
            {
                "code": "export default function run() { return 1; }",
                "runtime": tool_runtime({"messages": []}),
            },
        )
