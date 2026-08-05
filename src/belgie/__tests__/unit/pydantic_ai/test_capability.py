from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic_ai import Agent, ModelResponse
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelRequest, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from belgie import pydantic_ai
from belgie.pydantic_ai import (
    BelgieSandbox,
    BelgieSandboxError,
    BelgieSandboxExecutionError,
    BelgieSandboxSession,
    BelgieSandboxTimeoutError,
    BelgieSandboxUnavailableError,
)
from belgie.pydantic_ai._capability import DEFAULT_CAPABILITY_DESCRIPTION, DEFAULT_CAPABILITY_ID


def test_public_exports_are_limited() -> None:
    assert set(pydantic_ai.__all__) == {
        "BelgieSandbox",
        "BelgieSandboxError",
        "BelgieSandboxExecutionError",
        "BelgieSandboxSession",
        "BelgieSandboxTimeoutError",
        "BelgieSandboxUnavailableError",
    }
    assert BelgieSandbox.__name__ == "BelgieSandbox"
    assert BelgieSandboxSession.__name__ == "BelgieSandboxSession"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"allow_package_imports": 1}, "allow_package_imports must be a bool"),
        ({"allow_network": 1}, "allow_network must be a bool"),
        ({"enable_rendering": 1}, "enable_rendering must be a bool"),
        ({"max_old_generation_size_mb": 0}, "must be a positive integer or None"),
        ({"timeout": 0}, "must be a positive finite number"),
        ({"timeout": float("inf")}, "must be a positive finite number"),
        ({"max_output_bytes": 0}, "must be a positive integer"),
        ({"max_retries": -1}, "must be a non-negative integer"),
        ({"instructions": 1}, "must be a string or None"),
    ],
)
def test_validates_configuration(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        cast("Any", BelgieSandbox)(**kwargs)


def test_session_configuration_conflicts() -> None:
    with pytest.raises(ValueError, match="cannot be combined with `session`"):
        BelgieSandbox(session=BelgieSandboxSession(), enable_rendering=True)


def test_deferred_loading_has_stable_routing_metadata() -> None:
    capability = BelgieSandbox(defer_loading=True)
    assert capability.id == DEFAULT_CAPABILITY_ID
    assert capability.description == DEFAULT_CAPABILITY_DESCRIPTION


def test_instructions_reflect_configuration() -> None:
    strict = BelgieSandbox().get_instructions()
    assert strict is not None
    assert "imports are disabled" in strict
    assert "fetch` is disabled" in strict
    assert "@belgie/vite" not in strict
    assert "render_widget" not in strict

    open_profile = BelgieSandbox(
        allow_package_imports=True,
        allow_network=True,
        enable_rendering=True,
        timeout=12,
        max_output_bytes=100,
    ).get_instructions()
    assert open_profile is not None
    assert "imports are enabled" in open_profile
    assert "network access is enabled" in open_profile
    assert "@belgie/vite" in open_profile
    assert "render_widget" in open_profile
    assert "12s deadline" in open_profile

    assert BelgieSandbox(instructions="Custom.").get_instructions() == "Custom."
    assert BelgieSandbox(instructions="").get_instructions() is None
    session_instructions = BelgieSandbox(session=BelgieSandboxSession()).get_instructions()
    assert session_instructions is not None
    assert "caller-managed" in session_instructions


async def test_agent_executes_tool_and_preserves_other_tools(fake_belgie) -> None:
    seen_tools: list[set[str]] = []

    def echo(value: str) -> str:
        return value

    def model(messages: list[Any], info: Any) -> ModelResponse:
        seen_tools.append({tool.name for tool in info.function_tools})
        has_tool_return = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if not has_tool_return:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="run_typescript",
                        args={"code": "export default () => 42"},
                        tool_call_id="run-1",
                    ),
                ],
            )
        return ModelResponse(parts=[TextPart(content="done")])

    agent = cast("Any", Agent)(
        FunctionModel(model),
        tools=[echo],
        capabilities=[cast("Any", BelgieSandbox[None]())],
    )
    result = await agent.run("run TypeScript")

    assert result.output == "done"
    assert seen_tools[0] == {"echo", "run_typescript"}
    assert len(fake_belgie.runtimes) == 1
    assert fake_belgie.runtimes[0].exited


async def test_unused_capability_does_not_start_runtime(fake_belgie) -> None:
    model = TestModel(custom_output_text="done", call_tools=[])
    agent = Agent(model, capabilities=[BelgieSandbox()])

    assert (await agent.run("no code needed")).output == "done"
    assert fake_belgie.runtimes == []


async def test_deferred_capability_hides_tool_until_loaded(fake_belgie) -> None:
    model = TestModel(custom_output_text="done", call_tools=[])
    capability = BelgieSandbox(defer_loading=True)
    agent = Agent(model, capabilities=[capability])

    await agent.run("no code needed")

    assert capability.id == DEFAULT_CAPABILITY_ID
    assert model.last_model_request_parameters is not None
    tool_names = {tool.name for tool in model.last_model_request_parameters.function_tools}
    assert "load_capability" in tool_names
    assert "run_typescript" not in tool_names


async def test_durable_execution_is_rejected(fake_belgie) -> None:
    try:
        from pydantic_ai.durable_exec.dbos import DBOSDurability  # noqa: PLC0415
    except ImportError:
        pytest.skip("DBOS is not installed")

    with pytest.raises(UserError, match="does not support durable execution.*DBOSDurability"):
        Agent(
            TestModel(),
            name="belgie-durable-test",
            capabilities=[BelgieSandbox(), DBOSDurability()],
        )


def test_error_types_are_distinct() -> None:
    assert issubclass(BelgieSandboxExecutionError, BelgieSandboxError)
    assert issubclass(BelgieSandboxTimeoutError, BelgieSandboxExecutionError)
    assert issubclass(BelgieSandboxUnavailableError, BelgieSandboxError)
