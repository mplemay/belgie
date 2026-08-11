from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolReturn

from belgie.errors import BelgieError
from belgie.pydantic_ai import (
    BelgieSandbox,
    BelgieSandboxExecutionError,
    BelgieSandboxSession,
    BelgieSandboxUnavailableError,
)
from belgie.pydantic_ai._toolset import (
    DEFAULT_MAX_OUTPUT_BYTES,
    RUN_TYPESCRIPT_TOOL_NAME,
    BelgieSandboxToolset,
)


@asynccontextmanager
async def active_toolset(
    capability: BelgieSandbox[None] | None = None,
) -> AsyncIterator[BelgieSandboxToolset[None]]:
    toolset = (capability or BelgieSandbox[None]()).get_toolset()
    run_toolset = await toolset.for_run(cast("RunContext[None]", None))
    async with run_toolset:
        yield run_toolset


async def test_public_tool_definition_and_result(run_context, fake_belgie) -> None:
    async with active_toolset() as toolset:
        tools = await toolset.get_tools(run_context)
        assert list(tools) == [RUN_TYPESCRIPT_TOOL_NAME]
        tool = tools[RUN_TYPESCRIPT_TOOL_NAME]
        assert tool.tool_def.sequential is True
        assert tool.tool_def.metadata == {"code_arg_name": "code", "code_arg_language": "typescript"}
        assert tool.tool_def.parameters_json_schema["required"] == ["code"]
        result = await toolset.run_typescript("export default () => ({ ok: true })")

    assert isinstance(result, ToolReturn)
    assert result.return_value == {"ok": True}
    assert result.metadata == {
        "belgie_sandbox": True,
        "code_language": "typescript",
        "output_bytes": 11,
    }
    assert fake_belgie.scripts == ["export default () => ({ ok: true })"]


async def test_session_is_lazy_and_run_scoped(fake_belgie) -> None:
    async with active_toolset() as toolset:
        assert fake_belgie.runtimes == []
        await toolset.run_typescript("first")
        await toolset.run_typescript("second")
        assert len(fake_belgie.runtimes) == 1
        assert not fake_belgie.runtimes[0].exited

    assert fake_belgie.runtimes[0].exited
    async with active_toolset() as toolset:
        await toolset.run_typescript("third")
    assert len(fake_belgie.runtimes) == 2


async def test_owned_session_cleanup_can_be_retried(fake_belgie) -> None:
    toolset = BelgieSandbox[None]().get_toolset()
    run_toolset = await toolset.for_run(cast("RunContext[None]", None))
    await run_toolset.__aenter__()
    await run_toolset.run_typescript("code")
    fake_belgie.runtime_exit_error = RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await run_toolset.__aexit__(None, None, None)
    assert fake_belgie.runtimes[0].exit_calls == 1
    assert not fake_belgie.runtimes[0].exited

    fake_belgie.runtime_exit_error = None
    await run_toolset.__aexit__(None, None, None)
    assert fake_belgie.runtimes[0].exit_calls == 2
    assert fake_belgie.runtimes[0].exited
    with pytest.raises(BelgieSandboxExecutionError, match="not active"):
        await run_toolset.run_typescript("after close")


async def test_owned_session_startup_cleanup_can_be_retried(fake_belgie) -> None:
    toolset = BelgieSandbox[None]().get_toolset()
    run_toolset = await toolset.for_run(cast("RunContext[None]", None))
    await run_toolset.__aenter__()
    fake_belgie.start_error = RuntimeError("worker failed")
    fake_belgie.environment_exit_error = RuntimeError("cleanup failed")

    with pytest.raises(BelgieSandboxUnavailableError, match="Cleanup also failed.*cleanup failed"):
        await run_toolset.run_typescript("code")
    assert fake_belgie.environments[0].exit_calls == 1
    assert not fake_belgie.environments[0].exited

    fake_belgie.environment_exit_error = None
    await run_toolset.__aexit__(None, None, None)
    assert fake_belgie.environments[0].exit_calls == 2
    assert fake_belgie.environments[0].exited


async def test_script_failure_and_output_limit_are_model_retries(fake_belgie) -> None:
    async with active_toolset(BelgieSandbox(max_output_bytes=4)) as toolset:
        fake_belgie.script_error = BelgieError("bad syntax")
        with pytest.raises(ModelRetry, match="bad syntax"):
            await toolset.run_typescript("bad")

        fake_belgie.script_error = None
        fake_belgie.result = "large"
        with pytest.raises(ModelRetry, match="exceeding the 4-byte limit"):
            await toolset.run_typescript("large")

        fake_belgie.result = {1, 2}
        with pytest.raises(ModelRetry, match="invalid JSON"):
            await toolset.run_typescript("invalid")


async def test_unentered_toolset_is_a_caller_error(fake_belgie) -> None:
    toolset = BelgieSandbox[None]().get_toolset()
    with pytest.raises(BelgieSandboxExecutionError, match="not active"):
        await toolset.run_typescript("code")


async def test_injected_session_is_reused_and_not_closed(fake_belgie) -> None:
    session = BelgieSandboxSession()
    async with session:
        async with active_toolset(BelgieSandbox(session=session)) as toolset:
            await toolset.run_typescript("one")
        assert session.is_open
        async with active_toolset(BelgieSandbox(session=session)) as toolset:
            await toolset.run_typescript("two")
        assert len(fake_belgie.runtimes) == 1
    assert not session.is_open


async def test_unopened_injected_session_is_rejected(fake_belgie) -> None:
    with pytest.raises(BelgieSandboxExecutionError, match="not open"):
        async with active_toolset(BelgieSandbox(session=BelgieSandboxSession())):
            pass


async def test_concurrent_runs_have_separate_runtimes(fake_belgie) -> None:
    async def run_once(source: str) -> None:
        async with active_toolset() as toolset:
            await toolset.run_typescript(source)
            await asyncio.sleep(0)

    await asyncio.gather(run_once("alpha"), run_once("beta"))
    assert len(fake_belgie.runtimes) == 2
    assert all(runtime.exited for runtime in fake_belgie.runtimes)


async def test_cancelled_script_is_drained(fake_belgie) -> None:
    fake_belgie.hang = True
    fake_belgie.script_started = asyncio.Event()
    async with active_toolset() as toolset:
        task = asyncio.create_task(toolset.run_typescript("hang"))
        await fake_belgie.script_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert fake_belgie.cancelled


def test_toolset_defaults_are_stable() -> None:
    assert DEFAULT_MAX_OUTPUT_BYTES == 50 * 1024
