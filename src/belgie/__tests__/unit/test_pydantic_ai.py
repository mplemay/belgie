from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest
from pydantic_ai import FunctionToolset, RunContext, ToolReturn
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.models.test import TestModel
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.usage import RunUsage

from belgie._core import AsyncEnvironment
from belgie.pydantic_ai import (
    JavaScriptCodeMode,
    JavaScriptCodeModeToolset,
    RunJavaScriptTool,
    default_run_javascript_instructions,
)

SKILL_PATH: Final[Path] = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "use-belgie" / "SKILL.md"
CAPABILITY_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / ".agents"
    / "skills"
    / "use-belgie"
    / "capabilities"
    / "pydantic-ai-code-mode.md"
)


async def build_code_mode_toolset(
    wrapped: FunctionToolset[Any],
    *,
    tools: Any = "all",
    **toolset_kwargs: Any,
) -> tuple[JavaScriptCodeModeToolset[Any], RunContext[Any], dict[str, ToolsetTool[Any]]]:
    ctx: RunContext[Any] = RunContext(deps=None, model=TestModel(), usage=RunUsage(), run_step=0)
    toolset = JavaScriptCodeModeToolset(wrapped=wrapped, tool_selector=tools, **toolset_kwargs)
    tools_map = await toolset.get_tools(ctx)
    ctx.tool_manager = ToolManager(toolset=toolset, ctx=ctx, tools=tools_map)
    return toolset, ctx, tools_map


async def call_run_javascript(
    toolset: JavaScriptCodeModeToolset[Any],
    ctx: RunContext[Any],
    tools: dict[str, ToolsetTool[Any]],
    code: str,
) -> ToolReturn[Any]:
    result = await toolset.call_tool("run_javascript", {"code": code}, ctx, tools["run_javascript"])
    assert isinstance(result, ToolReturn)
    return result


def test_capability_wraps_toolset() -> None:
    wrapped = FunctionToolset()
    capability = JavaScriptCodeMode(tools=["search"], dependencies={"leftpad": "npm:left-pad@^1"})

    toolset = capability.get_wrapper_toolset(wrapped)

    assert isinstance(toolset, JavaScriptCodeModeToolset)
    assert toolset.tool_selector == ["search"]
    assert toolset.dependencies == {"leftpad": "npm:left-pad@^1"}


def test_capability_rejects_conflicting_instruction_modes() -> None:
    with pytest.raises(UserError, match="mutually exclusive"):
        JavaScriptCodeMode(instructions="append", dangerously_replace_instructions="replace")


async def test_run_javascript_calls_selected_tool() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset(include_return_schema=True)

    @wrapped.tool_plain
    def add(a: int, b: int) -> int:
        return a + b

    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    result = await call_run_javascript(toolset, ctx, tools, "return await add({ a: 2, b: 40 });")

    assert result.return_value == 42
    assert result.metadata["code_mode"] is True
    assert result.metadata["code_language"] == "javascript"
    assert len(result.metadata["tool_calls"]) == 1
    assert len(result.metadata["tool_returns"]) == 1


async def test_run_javascript_calls_tools_in_parallel() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset(include_return_schema=True)

    @wrapped.tool_plain
    def double(value: int) -> int:
        return value * 2

    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    result = await call_run_javascript(
        toolset,
        ctx,
        tools,
        "const values = await Promise.all([double({ value: 3 }), double({ value: 9 })]);\nreturn values;",
    )

    assert result.return_value == [6, 18]
    assert len(result.metadata["tool_calls"]) == 2


async def test_run_javascript_preserves_null_return() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset()
    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    result = await call_run_javascript(toolset, ctx, tools, "return null;")

    assert result.return_value is None


async def test_run_javascript_distinguishes_null_from_empty_object() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset()
    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    null_result = await call_run_javascript(toolset, ctx, tools, "return null;")
    empty_result = await call_run_javascript(toolset, ctx, tools, "return {};")

    assert null_result.return_value is None
    assert empty_result.return_value == {}


async def test_run_javascript_reuses_environment_for_replay_rounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset(include_return_schema=True)

    @wrapped.tool_plain
    def echo(value: str) -> str:
        return value

    install_calls = 0
    original_install = AsyncEnvironment.install

    def counting_install(self: AsyncEnvironment) -> object:
        nonlocal install_calls
        install_calls += 1
        return original_install(self)

    monkeypatch.setattr(AsyncEnvironment, "install", counting_install)

    toolset, ctx, tools = await build_code_mode_toolset(
        wrapped,
        dependencies={"leftpad": "npm:left-pad@^1"},
    )

    result = await call_run_javascript(
        toolset,
        ctx,
        tools,
        'const first = await echo({ value: "a" });\nreturn await echo({ value: first });',
    )

    assert result.return_value == "a"
    assert install_calls == 1


async def test_unselected_tools_stay_native() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset()

    @wrapped.tool_plain
    def selected() -> str:
        return "selected"

    @wrapped.tool_plain
    def native() -> str:
        return "native"

    _toolset, _ctx, tools = await build_code_mode_toolset(wrapped, tools=["selected"])
    run_tool = tools["run_javascript"]

    assert set(tools) == {"native", "run_javascript"}
    assert isinstance(run_tool, RunJavaScriptTool)
    assert "selected" in run_tool.callable_defs


async def test_deferred_tools_stay_native() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset(defer_loading=True)

    @wrapped.tool_plain
    def hidden() -> str:
        return "hidden"

    _toolset, _ctx, tools = await build_code_mode_toolset(wrapped)
    run_tool = tools["run_javascript"]

    assert set(tools) == {"hidden", "run_javascript"}
    assert tools["hidden"].tool_def.defer_loading is True
    assert isinstance(run_tool, RunJavaScriptTool)
    assert not run_tool.callable_defs


async def test_run_javascript_converts_tool_validation_error_to_model_retry() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset(include_return_schema=True)

    @wrapped.tool_plain
    def add(a: int, b: int) -> int:
        return a + b

    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    with pytest.raises(ModelRetry, match="validation failed"):
        await call_run_javascript(toolset, ctx, tools, 'return await add({ a: "not-an-int", b: 1 });')


async def test_run_javascript_converts_js_error_to_model_retry() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset()
    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    with pytest.raises(ModelRetry, match="boom"):
        await call_run_javascript(toolset, ctx, tools, 'throw new Error("boom");')


async def test_run_javascript_rejects_nondeterministic_tool_calls() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset(include_return_schema=True)

    @wrapped.tool_plain
    def echo(value: str) -> str:
        return value

    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    with pytest.raises(ModelRetry, match="deterministic"):
        await call_run_javascript(toolset, ctx, tools, "return await echo({ value: Math.random().toString() });")


async def test_run_javascript_rejects_unawaited_tool_calls() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset(include_return_schema=True)

    @wrapped.tool_plain
    def echo(value: str) -> str:
        return value

    toolset, ctx, tools = await build_code_mode_toolset(wrapped)

    with pytest.raises(ModelRetry, match="not awaited"):
        await call_run_javascript(toolset, ctx, tools, 'echo({ value: "ignored" });\nreturn "done";')


async def test_sanitized_tool_name_collision_warns() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset()

    @wrapped.tool_plain(name="get-weather")
    def get_weather_hyphen() -> str:
        return "hyphen"

    @wrapped.tool_plain(name="get.weather")
    def get_weather_dot() -> str:
        return "dot"

    with pytest.warns(UserWarning, match="collides"):
        _toolset, _ctx, tools = await build_code_mode_toolset(wrapped)
    run_tool = tools["run_javascript"]

    assert isinstance(run_tool, RunJavaScriptTool)
    assert list(run_tool.callable_defs) == ["get_weather"]


async def test_run_javascript_name_is_reserved() -> None:
    wrapped: FunctionToolset[Any] = FunctionToolset()

    @wrapped.tool_plain
    def run_javascript() -> str:
        return "conflict"

    with pytest.raises(UserError, match="reserved"):
        await build_code_mode_toolset(wrapped)


def test_default_instructions_explain_javascript_contract() -> None:
    instructions = default_run_javascript_instructions()

    assert "async JavaScript function body" in instructions
    assert 'await import("pkg")' in instructions
    assert "await search({ query" in instructions


def test_skill_documents_pydantic_ai_capability() -> None:
    assert CAPABILITY_PATH.exists()
    skill = SKILL_PATH.read_text(encoding="utf-8")
    capability = CAPABILITY_PATH.read_text(encoding="utf-8")

    assert "capabilities/pydantic-ai-code-mode.md" in skill
    assert "belgie[pydantic-ai]" in capability
    assert "JavaScriptCodeMode" in capability
