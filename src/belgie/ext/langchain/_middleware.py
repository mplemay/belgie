from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from belgie.errors import BelgieError
from belgie.ext.core._options import BelgieOptions
from belgie.ext.core._run_code import (
    BELGIE_TOOL_NAMES,
    DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
    DEFAULT_BELGIE_CAPABILITY_ID,
    apply_defer_loading_defaults,
    format_script_failure,
    resolved_description,
)
from belgie.ext.core._runtime import BelgieRuntimeSession
from belgie.ext.langchain._state import (
    BELGIE_RUNTIME_SESSION_STATE_KEY,
    BelgieAgentState,
    session_from_state,
)
from belgie.ext.langchain._tools import build_load_belgie_tool, build_run_code_tool

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import ModelRequest, ModelResponse
    from langchain_core.tools import BaseTool
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.runtime import Runtime
    from langgraph.types import Command


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
        if not self.defer_loading:
            return [run_code_tool]
        load_tool = build_load_belgie_tool(
            capability_id=capability_id,
            description=DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
        )
        return [load_tool, run_code_tool]

    def _new_session(self) -> BelgieRuntimeSession:
        return BelgieRuntimeSession(**self.options_kwargs())

    def before_agent(self, state: BelgieAgentState, runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        session = self._new_session()
        asyncio.run(session.__aenter__())
        return {BELGIE_RUNTIME_SESSION_STATE_KEY: session}

    async def abefore_agent(
        self,
        state: BelgieAgentState,  # noqa: ARG002
        runtime: Runtime[Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        session = self._new_session()
        await session.__aenter__()
        return {BELGIE_RUNTIME_SESSION_STATE_KEY: session}

    def after_agent(self, state: BelgieAgentState, runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        self._close_session(session_from_state(state))
        return {BELGIE_RUNTIME_SESSION_STATE_KEY: None}

    async def aafter_agent(
        self,
        state: BelgieAgentState,
        runtime: Runtime[Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        await self._aclose_session(session_from_state(state))
        return {BELGIE_RUNTIME_SESSION_STATE_KEY: None}

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
        if request.tool_call["name"] not in BELGIE_TOOL_NAMES:
            return handler(request)
        try:
            return handler(request)
        except (BelgieError, TimeoutError, RuntimeError) as error:
            return self._tool_error_message(request, error)

    async def _wrap_belgie_tool_call_async(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] not in BELGIE_TOOL_NAMES:
            return await handler(request)
        try:
            return await handler(request)
        except (BelgieError, TimeoutError, RuntimeError) as error:
            return self._tool_error_message(request, error)

    def _tool_error_message(self, request: ToolCallRequest, error: Exception) -> ToolMessage:
        return ToolMessage(
            content=format_script_failure(error),
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
