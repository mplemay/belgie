from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

from langchain.tools import tool
from pydantic import BaseModel, Field

from belgie.capabilities.core._run_code import (
    LOAD_BELGIE_TOOL_NAME,
    RUN_CODE_TOOL_NAME,
)
from belgie.capabilities.core._runtime import SESSION_NOT_ENTERED_MESSAGE, BelgieRuntimeSession
from belgie.errors import BelgieError

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.tools import BaseTool

SESSION_NOT_READY_MESSAGE: Final[str] = "Belgie middleware runtime session is not active."
SCRIPT_FAILURE_PREFIX: Final[str] = "Belgie script execution failed:\n"


class RunCodeInput(BaseModel):
    code: str = Field(description="The JavaScript or TypeScript belgie.Script module source to execute.")


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


def build_run_code_tool(
    *,
    session_getter: Callable[[], BelgieRuntimeSession | None],
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
    def run_code(code: str) -> Any:  # noqa: ANN401
        session = session_getter()
        if session is None:
            raise RuntimeError(SESSION_NOT_ENTERED_MESSAGE)
        return _run_script_sync(session, code)

    return run_code


def build_load_belgie_tool(
    *,
    capability_id: str,
    description: str,
    on_load: Callable[[], None],
) -> BaseTool:
    @tool(
        LOAD_BELGIE_TOOL_NAME,
        description=(
            f"Load the Belgie JavaScript/TypeScript sandbox capability. Available capability id: {capability_id}."
        ),
        args_schema=LoadBelgieInput,
    )
    def load_belgie(capability_id: str) -> str:  # noqa: ARG001
        on_load()
        return description

    return load_belgie


def format_tool_error(error: Exception) -> str:
    if isinstance(error, BelgieError):
        return f"{SCRIPT_FAILURE_PREFIX}{error}"
    return str(error)
