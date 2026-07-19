from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from belgie.agent import (
    BUILD_WIDGET_TOOL_NAME,
    BelgieOptions,
    BelgieRuntimeSession,
    format_script_failure,
    format_widget_failure,
)
from belgie.agent._run_code import (
    DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
    DEFAULT_BELGIE_CAPABILITY_ID,
    apply_defer_loading_defaults,
    resolved_description,
)
from belgie.errors import BelgieError
from belgie.langchain._state import (
    BELGIE_RUNTIME_SESSION_STATE_KEY,
    BELGIE_WIDGET_SESSION_STATE_KEY,
    BelgieAgentState,
    session_from_state,
    widget_session_from_state,
)
from belgie.langchain._tools import build_load_belgie_tool, build_run_code_tool, build_widget_tool

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import ModelRequest, ModelResponse
    from langchain_core.tools import BaseTool
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.runtime import Runtime
    from langgraph.types import Command

    from belgie.widget._builder import _AsyncWidgetSession


@dataclass(kw_only=True)
class BelgieMiddleware(BelgieOptions, AgentMiddleware[BelgieAgentState]):
    state_schema: type[BelgieAgentState] = field(default=BelgieAgentState, init=False, repr=False)
    tools: list[BaseTool] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        apply_defer_loading_defaults(self)
        self.validate()
        object.__setattr__(self, "tools", self._create_tools())

    def _create_tools(self) -> list[BaseTool]:
        capability_id = self.capability_id or DEFAULT_BELGIE_CAPABILITY_ID
        description = resolved_description(self)
        run_code_tool = build_run_code_tool(
            description=description,
            defer_loading=self.defer_loading,
        )
        tools = [run_code_tool]
        if self.widget_builder is not None:
            tools.append(build_widget_tool(defer_loading=self.defer_loading))
        if not self.defer_loading:
            return tools
        load_tool = build_load_belgie_tool(
            capability_id=capability_id,
            description=DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
        )
        return [load_tool, *tools]

    def _new_session(self) -> BelgieRuntimeSession:
        return BelgieRuntimeSession(**self.options_kwargs())

    def before_agent(self, state: BelgieAgentState, runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        session = self._new_session()
        asyncio.run(session.__aenter__())
        widget_session = self.widget_builder.new_async_session() if self.widget_builder is not None else None
        try:
            if widget_session is not None:
                asyncio.run(widget_session.__aenter__())
        except BaseException:
            asyncio.run(session.__aexit__(None, None, None))
            raise
        return {
            BELGIE_RUNTIME_SESSION_STATE_KEY: session,
            BELGIE_WIDGET_SESSION_STATE_KEY: widget_session,
        }

    async def abefore_agent(
        self,
        state: BelgieAgentState,  # noqa: ARG002
        runtime: Runtime[Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        session = self._new_session()
        await session.__aenter__()
        widget_session = self.widget_builder.new_async_session() if self.widget_builder is not None else None
        try:
            if widget_session is not None:
                await widget_session.__aenter__()
        except BaseException:
            await session.__aexit__(None, None, None)
            raise
        return {
            BELGIE_RUNTIME_SESSION_STATE_KEY: session,
            BELGIE_WIDGET_SESSION_STATE_KEY: widget_session,
        }

    def after_agent(self, state: BelgieAgentState, runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        self._close_widget_session(widget_session_from_state(state))
        self._close_session(session_from_state(state))
        return {BELGIE_RUNTIME_SESSION_STATE_KEY: None, BELGIE_WIDGET_SESSION_STATE_KEY: None}

    async def aafter_agent(
        self,
        state: BelgieAgentState,
        runtime: Runtime[Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        await self._aclose_widget_session(widget_session_from_state(state))
        await self._aclose_session(session_from_state(state))
        return {BELGIE_RUNTIME_SESSION_STATE_KEY: None, BELGIE_WIDGET_SESSION_STATE_KEY: None}

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(request.override(tools=cast("list[BaseTool | dict[str, Any]]", self.tools)))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Any],
    ) -> ModelResponse[Any]:
        return await handler(request.override(tools=cast("list[BaseTool | dict[str, Any]]", self.tools)))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        return self._wrap_belgie_tool_call(request, handler)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        return await self._wrap_belgie_tool_call_async(request, handler)

    def _wrap_belgie_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] not in {tool.name for tool in self.tools}:
            return handler(request)
        try:
            return handler(request)
        except (BelgieError, TimeoutError, RuntimeError, ValueError) as error:
            return self._tool_error_message(request, error)

    async def _wrap_belgie_tool_call_async(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] not in {tool.name for tool in self.tools}:
            return await handler(request)
        try:
            return await handler(request)
        except (BelgieError, TimeoutError, RuntimeError, ValueError) as error:
            return self._tool_error_message(request, error)

    def _tool_error_message(self, request: ToolCallRequest, error: Exception) -> ToolMessage:
        formatter = (
            format_widget_failure if request.tool_call["name"] == BUILD_WIDGET_TOOL_NAME else format_script_failure
        )
        return ToolMessage(
            content=formatter(error),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )

    def _close_session(self, session: BelgieRuntimeSession | None) -> None:
        if session is None:
            return
        asyncio.run(session.__aexit__(None, None, None))

    async def _aclose_session(self, session: BelgieRuntimeSession | None) -> None:
        if session is None:
            return
        await session.__aexit__(None, None, None)

    def _close_widget_session(self, session: _AsyncWidgetSession | None) -> None:
        if session is None:
            return
        asyncio.run(session.__aexit__(None, None, None))

    async def _aclose_widget_session(self, session: _AsyncWidgetSession | None) -> None:
        if session is None:
            return
        await session.__aexit__(None, None, None)
