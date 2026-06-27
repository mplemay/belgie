from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from belgie.capabilities.core._options import BelgieOptions
from belgie.capabilities.core._run_code import (
    DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
    DEFAULT_BELGIE_CAPABILITY_ID,
    LOAD_BELGIE_TOOL_NAME,
    RUN_CODE_TOOL_NAME,
    resolved_description,
)
from belgie.capabilities.core._runtime import BelgieRuntimeSession
from belgie.capabilities.langchain._tools import (
    build_load_belgie_tool,
    build_run_code_tool,
    format_tool_error,
)
from belgie.errors import BelgieError

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain.agents.middleware import AgentState
    from langchain.agents.middleware.types import ModelRequest, ModelResponse
    from langchain_core.tools import BaseTool
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.runtime import Runtime
    from langgraph.types import Command


@dataclass(kw_only=True)
class BelgieMiddleware(BelgieOptions, AgentMiddleware):
    tools: list[BaseTool] = field(default_factory=list, init=False, repr=False)
    _session: BelgieRuntimeSession | None = field(default=None, init=False, repr=False)
    _belgie_loaded: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.defer_loading and self.capability_id is None:
            self.capability_id = DEFAULT_BELGIE_CAPABILITY_ID
        self.validate()
        object.__setattr__(self, "tools", self._create_tools())

    def _create_tools(self) -> list[BaseTool]:
        capability_id = self.capability_id or DEFAULT_BELGIE_CAPABILITY_ID
        description = resolved_description(self)
        run_code_tool = build_run_code_tool(
            session_getter=lambda: self._session,
            description=description,
            defer_loading=self.defer_loading,
        )
        if not self.defer_loading:
            return [run_code_tool]
        load_tool = build_load_belgie_tool(
            capability_id=capability_id,
            description=DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
            on_load=self._mark_loaded,
        )
        return [load_tool, run_code_tool]

    def _mark_loaded(self) -> None:
        self._belgie_loaded = True

    def _reset_run_state(self) -> None:
        self._belgie_loaded = False

    def _visible_tools(self) -> list[BaseTool | dict[str, Any]]:
        return cast("list[BaseTool | dict[str, Any]]", list(self.tools))

    def before_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        self._reset_run_state()
        self._session = BelgieRuntimeSession(**self.options_kwargs())
        asyncio.run(self._session.__aenter__())
        return None

    async def abefore_agent(
        self,
        state: AgentState[Any],  # noqa: ARG002
        runtime: Runtime[Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        self._reset_run_state()
        self._session = BelgieRuntimeSession(**self.options_kwargs())
        await self._session.__aenter__()
        return None

    def after_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        self._close_session()
        return None

    async def aafter_agent(
        self,
        state: AgentState[Any],  # noqa: ARG002
        runtime: Runtime[Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        await self._aclose_session()
        return None

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(request.override(tools=self._visible_tools()))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Any],
    ) -> ModelResponse[Any]:
        return await handler(request.override(tools=self._visible_tools()))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] not in {RUN_CODE_TOOL_NAME, LOAD_BELGIE_TOOL_NAME}:
            return handler(request)
        try:
            return handler(request)
        except (BelgieError, TimeoutError, RuntimeError) as error:
            return self._tool_error_message(request, error)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] not in {RUN_CODE_TOOL_NAME, LOAD_BELGIE_TOOL_NAME}:
            return await handler(request)
        try:
            return await handler(request)
        except (BelgieError, TimeoutError, RuntimeError) as error:
            return self._tool_error_message(request, error)

    def _tool_error_message(self, request: ToolCallRequest, error: Exception) -> ToolMessage:
        return ToolMessage(
            content=format_tool_error(error),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )

    def _close_session(self) -> None:
        session = self._session
        self._session = None
        if session is None:
            return
        asyncio.run(session.__aexit__(None, None, None))

    async def _aclose_session(self) -> None:
        session = self._session
        self._session = None
        if session is None:
            return
        await session.__aexit__(None, None, None)

    def resolved_description(self) -> str:
        return resolved_description(self)
