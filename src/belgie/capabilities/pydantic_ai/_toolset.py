from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Annotated, Any, Final, NotRequired, Self, TypedDict, cast

from pydantic import Field, TypeAdapter
from pydantic_ai import AbstractToolset, RunContext, ToolDefinition, WrapperToolset
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets.abstract import SchemaValidatorProt, ToolsetTool

from belgie import Environment, JsonInput, JsonOutput, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie._core import AsyncEnvironment, AsyncRuntime, SyncEnvironment
from belgie.errors import BelgieError

type BelgieEnvironment = Environment | SyncEnvironment | AsyncEnvironment
type RunCodeRunner = Callable[[JsonInput], Awaitable[JsonOutput]]
type AsyncExitArgs = tuple[
    type[BaseException] | None,
    BaseException | None,
    TracebackType | None,
]


class RunCodeArguments(TypedDict):
    code: Annotated[str, Field(description="The JavaScript code to execute.")]
    restart: NotRequired[
        Annotated[
            bool,
            Field(description="Set to true to reset the JavaScript state object before executing code."),
        ]
    ]


RUN_CODE_TOOL_NAME: Final[str] = "run_code"
RUN_CODE_ADAPTER: Final[TypeAdapter[RunCodeArguments]] = TypeAdapter(RunCodeArguments)
RUN_CODE_JSON_SCHEMA: Final[dict[str, Any]] = RUN_CODE_ADAPTER.json_schema()
RUN_CODE_ARGS_VALIDATOR: Final[SchemaValidatorProt] = cast("SchemaValidatorProt", RUN_CODE_ADAPTER.validator)
RUN_CODE_METADATA: Final[dict[str, str]] = {
    "code_arg_name": "code",
    "code_arg_language": "javascript",
}
DEFAULT_RUNTIME_OPTIONS: Final[RuntimeOptions] = RuntimeOptions(
    permissions=RuntimePermissions(allow_net=[]),
)
RUN_CODE_DESCRIPTION: Final[str] = """\
Write and run JavaScript in a belgie sandbox.

The code runs inside an async JavaScript function, so `await fetch(...)` is available \
when this capability uses its default runtime configuration. The sandbox exposes a persistent \
`state` object for this agent run; store values on `state` when you need them in a later \
`run_code` call. Set `restart: true` to clear that state.

Important restrictions:
- Only JavaScript is supported.
- External pydantic-ai tools are not available inside the sandbox.
- Return values must be JSON-serializable.
- Use `return` for the value you want to send back; `console.log` is only for supplementary output.

Examples:

```javascript
const response = await fetch("https://hacker-news.firebaseio.com/v0/topstories.json");
const ids = await response.json();
state.topIds = ids.slice(0, 20);
return state.topIds;
```
"""
RUN_CODE_SCRIPT: Final[str] = r"""
const STATE_KEY = Symbol.for("belgie.pydantic_ai.state");

function stateContainer() {
  if (!globalThis[STATE_KEY]) {
    globalThis[STATE_KEY] = {};
  }
  return globalThis[STATE_KEY];
}

function clearState(state) {
  for (const key of Object.keys(state)) {
    delete state[key];
  }
}

function formatLogValue(value) {
  if (typeof value === "string") {
    return value;
  }
  try {
    const formatted = JSON.stringify(value);
    return formatted === undefined ? String(value) : formatted;
  } catch {
    return String(value);
  }
}

function toJsonValue(value) {
  if (value === undefined) {
    return null;
  }
  try {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) {
      return null;
    }
    return JSON.parse(encoded);
  } catch (error) {
    throw new TypeError(`run_code returned a value that is not JSON-serializable: ${error.message}`);
  }
}

export default async function run(input) {
  const state = stateContainer();
  if (input.restart) {
    clearState(state);
  }

  const logs = [];
  const originalLog = console.log;
  const originalWarn = console.warn;
  console.log = (...values) => logs.push(values.map(formatLogValue).join(" "));
  console.warn = (...values) => logs.push(values.map(formatLogValue).join(" "));

  try {
    const execute = new Function("state", `"use strict"; return (async () => {\n${input.code}\n})();`);
    const result = toJsonValue(await execute(state));
    if (logs.length === 0) {
      return result ?? {};
    }
    if (result === null) {
      return { output: logs.join("\n") };
    }
    return { output: logs.join("\n"), result };
  } finally {
    console.log = originalLog;
    console.warn = originalWarn;
  }
}
"""

DEFAULT_RUN_CODE_INSTRUCTIONS: Final[str] = RUN_CODE_DESCRIPTION
INSTRUCTIONS_CONFLICT_MESSAGE: Final[str] = (
    "`instructions` and `dangerously_replace_instructions` are mutually exclusive: "
    "`instructions` appends to the built-in prose, while "
    "`dangerously_replace_instructions` replaces it."
)
RUNTIME_ENVIRONMENT_CONFLICT_MESSAGE: Final[str] = (
    "`runtime` cannot be combined with `environment` or `runtime_options`."
)
UNSUPPORTED_TOOL_MESSAGE: Final[str] = "Belgie capability only supports the {tool_name!r} tool."
TOOLSET_NOT_ENTERED_MESSAGE: Final[str] = "BelgieToolset must be entered before calling tools."


class _BelgieOptionsKwargs(TypedDict):
    max_retries: int
    runtime: Runtime | None
    environment: BelgieEnvironment | None
    runtime_options: RuntimeOptions | None
    instructions: str | None
    dangerously_replace_instructions: str | None


@dataclass(kw_only=True)
class _BelgieOptions:
    max_retries: int = 3
    runtime: Runtime | None = None
    environment: BelgieEnvironment | None = None
    runtime_options: RuntimeOptions | None = None
    instructions: str | None = None
    dangerously_replace_instructions: str | None = None

    def validate(self) -> None:
        if self.instructions is not None and self.dangerously_replace_instructions is not None:
            raise UserError(INSTRUCTIONS_CONFLICT_MESSAGE)
        if self.runtime is not None and (self.environment is not None or self.runtime_options is not None):
            raise UserError(RUNTIME_ENVIRONMENT_CONFLICT_MESSAGE)

    def options_kwargs(self) -> _BelgieOptionsKwargs:
        return {
            "max_retries": self.max_retries,
            "runtime": self.runtime,
            "environment": self.environment,
            "runtime_options": self.runtime_options,
            "instructions": self.instructions,
            "dangerously_replace_instructions": self.dangerously_replace_instructions,
        }


@dataclass(kw_only=True)
class BelgieToolset(_BelgieOptions, WrapperToolset[AgentDepsT]):
    _exit_stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _runner: RunCodeRunner | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.validate()

    async def for_run(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:  # noqa: ARG002
        return replace(self)

    async def for_run_step(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:  # noqa: ARG002
        return self

    async def get_instructions(self, ctx: RunContext[AgentDepsT]) -> None:  # noqa: ARG002
        # Wrapped toolset instructions must not leak into the system prompt.
        return None

    async def __aenter__(self) -> Self:
        if self._exit_stack is not None:
            return self

        stack = AsyncExitStack()
        try:
            active_runtime = await self._enter_runtime(stack)
            self._runner = active_runtime(Script(RUN_CODE_SCRIPT))
            self._exit_stack = stack
        except BaseException:
            await stack.aclose()
            raise
        return self

    async def __aexit__(self, *args: object) -> bool | None:
        stack = self._exit_stack
        self._exit_stack = None
        self._runner = None
        if stack is None:
            return None
        return await stack.__aexit__(*cast("AsyncExitArgs", args))

    async def get_tools(self, ctx: RunContext[AgentDepsT]) -> dict[str, ToolsetTool[AgentDepsT]]:  # noqa: ARG002
        return {
            RUN_CODE_TOOL_NAME: ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name=RUN_CODE_TOOL_NAME,
                    description=self._resolved_description(),
                    parameters_json_schema=RUN_CODE_JSON_SCHEMA,
                    metadata=RUN_CODE_METADATA,
                    sequential=True,
                ),
                max_retries=self.max_retries,
                args_validator=RUN_CODE_ARGS_VALIDATOR,
            ),
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDepsT],  # noqa: ARG002
        tool: ToolsetTool[AgentDepsT],  # noqa: ARG002
    ) -> Any:  # noqa: ANN401
        if name != RUN_CODE_TOOL_NAME:
            raise UserError(UNSUPPORTED_TOOL_MESSAGE.format(tool_name=RUN_CODE_TOOL_NAME))
        if self._runner is None:
            raise UserError(TOOLSET_NOT_ENTERED_MESSAGE)

        try:
            return_value = await self._runner(
                {
                    "code": tool_args["code"],
                    "restart": tool_args.get("restart", False),
                },
            )
        except BelgieError as error:
            retry_message = f"JavaScript execution failed:\n{error}"
            raise ModelRetry(retry_message) from error

        return ToolReturn(
            return_value=return_value,
            metadata={"belgie": True, "code_language": "javascript"},
        )

    async def _enter_runtime(self, stack: AsyncExitStack) -> AsyncRuntime:
        if self.runtime is not None:
            return await stack.enter_async_context(self.runtime)

        options = self.runtime_options or DEFAULT_RUNTIME_OPTIONS
        if self.environment is None:
            active_environment = await stack.enter_async_context(Environment())
        elif isinstance(self.environment, Environment):
            active_environment = await stack.enter_async_context(self.environment)
        else:
            active_environment = self.environment

        return await stack.enter_async_context(Runtime(env=active_environment, options=options))

    def _resolved_description(self) -> str:
        if self.dangerously_replace_instructions is not None:
            return self.dangerously_replace_instructions
        if self.instructions is None:
            return RUN_CODE_DESCRIPTION
        return f"{RUN_CODE_DESCRIPTION}\n\n{self.instructions}"
