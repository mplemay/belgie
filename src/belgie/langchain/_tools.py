import asyncio
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from belgie.agent import (
    BUILD_WIDGET_TOOL_NAME,
    LOAD_BELGIE_TOOL_NAME,
    RUN_CODE_TOOL_NAME,
    BelgieRuntimeSession,
    BuildWidgetInput,
    RunCodeInput,
    widget_build_summary,
)
from belgie.agent._build_widget import BUILD_WIDGET_DESCRIPTION
from belgie.agent._run_code import load_belgie_tool_description
from belgie.agent._runtime import SESSION_NOT_ENTERED_MESSAGE
from belgie.langchain._state import BelgieAgentState, session_from_state, widget_session_from_state
from belgie.widget import WidgetBundle, WidgetSource
from belgie.widget._builder import _AsyncWidgetSession


class LoadBelgieInput(BaseModel):
    capability_id: str = Field(description="The Belgie capability id to load.")


def _run_script_sync(session: BelgieRuntimeSession, code: str) -> Any:  # noqa: ANN401
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(session.run_script(code))
    msg = (
        "Belgie run_code cannot execute from an active event loop with synchronous agent invocation. "
        "Use agent.ainvoke() instead."
    )
    raise RuntimeError(msg)


def _build_widget_sync(session: _AsyncWidgetSession, source: WidgetSource) -> WidgetBundle:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(session.build(source))
    msg = (
        "Belgie build_widget cannot execute from an active event loop with synchronous agent invocation. "
        "Use agent.ainvoke() instead."
    )
    raise RuntimeError(msg)


def build_run_code_tool(
    *,
    description: str,
    defer_loading: bool = False,
) -> BaseTool:
    extras = {"defer_loading": True} if defer_loading else None

    @tool(
        RUN_CODE_TOOL_NAME,
        description=description,
        args_schema=RunCodeInput,
        extras=extras,
    )
    def run_code(code: str, runtime: ToolRuntime[Any, BelgieAgentState]) -> Any:  # noqa: ANN401
        session = session_from_state(runtime.state)
        if session is None:
            raise RuntimeError(SESSION_NOT_ENTERED_MESSAGE)
        return _run_script_sync(session, code)

    return run_code


def build_widget_tool(*, defer_loading: bool = False) -> BaseTool:
    extras = {"defer_loading": True} if defer_loading else None

    @tool(
        BUILD_WIDGET_TOOL_NAME,
        description=BUILD_WIDGET_DESCRIPTION,
        args_schema=BuildWidgetInput,
        extras=extras,
        response_format="content_and_artifact",
    )
    def build_widget(
        widget: str,
        files: dict[str, str],
        runtime: ToolRuntime[Any, BelgieAgentState],
    ) -> tuple[str, WidgetBundle]:
        session = widget_session_from_state(runtime.state)
        if session is None:
            raise RuntimeError(SESSION_NOT_ENTERED_MESSAGE)
        parsed = BuildWidgetInput(widget=widget, files=files)
        bundle = _build_widget_sync(session, WidgetSource(widget=parsed.widget, files=parsed.files))
        return widget_build_summary(bundle, parsed), bundle

    return build_widget


def build_load_belgie_tool(
    *,
    capability_id: str,
    description: str,
) -> BaseTool:
    @tool(
        LOAD_BELGIE_TOOL_NAME,
        description=load_belgie_tool_description(capability_id),
        args_schema=LoadBelgieInput,
    )
    def load_belgie(capability_id: str) -> str:  # noqa: ARG001
        return description

    return load_belgie
