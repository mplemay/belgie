from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING, Any, Final, cast

from pydantic_ai import Agent, FunctionToolset, RunContext, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.usage import RunUsage

if TYPE_CHECKING:
    from pydantic_ai.toolsets.abstract import ToolsetTool

from belgie.pydantic_ai import JavaScriptCodeMode, JavaScriptCodeModeToolset

PARALLEL_WEATHER_JAVASCRIPT: Final[str] = """\
const [paris, tokyo] = await Promise.all([
  get_weather({ city: "Paris" }),
  get_weather({ city: "Tokyo" }),
]);
const paris_c = await convert_temp({ fahrenheit: paris.temp_f });
const tokyo_c = await convert_temp({ fahrenheit: tokyo.temp_f });
return { paris: paris_c, tokyo: tokyo_c };
"""

MODEL: Final[str] = "openai:gpt-5-mini"
OPENAI_API_KEY_ENV: Final[str] = "OPENAI_API_KEY"

AGENT_PROMPT: Final[str] = "What's the weather in Paris and Tokyo, in Celsius?"


def get_weather(city: str) -> dict[str, object]:
    return {"city": city, "temp_f": 72, "condition": "sunny"}


def convert_temp(fahrenheit: float) -> float:
    return round((fahrenheit - 32) * 5 / 9, 1)


def build_agent(model: str) -> Agent[None, str]:
    agent: Agent[None, str] = Agent(
        model,
        capabilities=[JavaScriptCodeMode()],
        instructions=(
            "Use run_javascript to call tools. Prefer one script that fetches data in "
            "parallel and returns JSON-safe results."
        ),
    )
    agent.tool_plain(get_weather)
    agent.tool_plain(convert_temp)
    return agent


async def _build_code_mode_toolset() -> tuple[
    JavaScriptCodeModeToolset[Any],
    RunContext[Any],
    dict[str, ToolsetTool[Any]],
]:
    wrapped: FunctionToolset[Any] = FunctionToolset(include_return_schema=True)
    wrapped.tool_plain(get_weather)
    wrapped.tool_plain(convert_temp)

    ctx: RunContext[Any] = RunContext(deps=None, model=TestModel(), usage=RunUsage(), run_step=0)
    toolset = JavaScriptCodeModeToolset(wrapped=wrapped)
    tools_map = await toolset.get_tools(ctx)
    ctx.tool_manager = ToolManager(toolset=toolset, ctx=ctx, tools=tools_map)
    return toolset, ctx, tools_map


async def run_javascript_parallel_demo() -> dict[str, float]:
    toolset, ctx, tools = await _build_code_mode_toolset()
    result = await toolset.call_tool(
        "run_javascript",
        {"code": PARALLEL_WEATHER_JAVASCRIPT},
        ctx,
        tools["run_javascript"],
    )
    if not isinstance(result, ToolReturn):
        message = "run_javascript did not return a ToolReturn"
        raise TypeError(message)
    return cast("dict[str, float]", result.return_value)


async def _main() -> None:
    if OPENAI_API_KEY_ENV not in os.environ:
        print(f"Set {OPENAI_API_KEY_ENV}", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    agent = build_agent(MODEL)
    result = await agent.run(AGENT_PROMPT)
    print(result.output)  # noqa: T201


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
