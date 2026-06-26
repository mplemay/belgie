from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Annotated, Any, Final, Self, TypedDict, cast

from pydantic import Field, TypeAdapter
from pydantic_ai import AbstractToolset, RunContext, ToolDefinition, WrapperToolset
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets.abstract import SchemaValidatorProt, ToolsetTool

from belgie import Environment, JsonOutput, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie._core import AsyncEnvironment, AsyncRuntime, SyncEnvironment
from belgie.errors import BelgieError

type BelgieEnvironment = Environment | SyncEnvironment | AsyncEnvironment
type AsyncExitArgs = tuple[
    type[BaseException] | None,
    BaseException | None,
    TracebackType | None,
]


class RunCodeArguments(TypedDict):
    code: Annotated[str, Field(description="The JavaScript or TypeScript belgie.Script module source to execute.")]


RUN_CODE_TOOL_NAME: Final[str] = "run_code"
RUN_CODE_ADAPTER: Final[TypeAdapter[RunCodeArguments]] = TypeAdapter(RunCodeArguments)
RUN_CODE_JSON_SCHEMA: Final[dict[str, Any]] = RUN_CODE_ADAPTER.json_schema()
RUN_CODE_ARGS_VALIDATOR: Final[SchemaValidatorProt] = cast("SchemaValidatorProt", RUN_CODE_ADAPTER.validator)
RUN_CODE_METADATA: Final[dict[str, str]] = {
    "code_arg_name": "code",
    "code_arg_language": "typescript",
}
DEFAULT_RUNTIME_OPTIONS: Final[RuntimeOptions] = RuntimeOptions(
    permissions=RuntimePermissions(allow_net=[]),
)
RUN_CODE_DESCRIPTION: Final[str] = """\
Write and run a belgie.Script module in a sandbox.

The code is complete JavaScript or TypeScript module source for Belgie's embedded Deno-powered \
runtime. Belgie treats inline source as TypeScript, so type annotations are supported and plain \
JavaScript is valid. Export a callable function; prefer `export default async function run() { ... }`, \
or use `export function run() { ... }`.

This is a Deno environment, not Node.js. Use Deno-style imports such as `npm:pkg@version`, \
`jsr:@scope/pkg@version`, or full URLs. `await fetch(...)` is available when this capability uses \
its default runtime configuration.

Important restrictions:
- External pydantic-ai tools are not available inside the sandbox.
- Return values must be JSON-serializable.
- Use `return` from the exported function for the value you want to send back.

Examples:

```typescript
export default async function run(): Promise<number[]> {
  const response = await fetch("https://hacker-news.firebaseio.com/v0/topstories.json");
  const ids: number[] = await response.json();
  return ids.slice(0, 20);
}
```
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
    _active_environment: BelgieEnvironment | None = field(default=None, init=False, repr=False)
    _active_runtime: AsyncRuntime | None = field(default=None, init=False, repr=False)

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
            if self.runtime is None:
                self._active_environment = await self._enter_environment(stack)
            else:
                self._active_runtime = await stack.enter_async_context(self.runtime)
            self._exit_stack = stack
        except BaseException:
            await stack.aclose()
            raise
        return self

    async def __aexit__(self, *args: object) -> bool | None:
        stack = self._exit_stack
        self._exit_stack = None
        self._active_environment = None
        self._active_runtime = None
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
        if self._exit_stack is None:
            raise UserError(TOOLSET_NOT_ENTERED_MESSAGE)

        try:
            return_value = await self._run_script(tool_args["code"])
        except BelgieError as error:
            retry_message = f"Belgie script execution failed:\n{error}"
            raise ModelRetry(retry_message) from error

        return ToolReturn(
            return_value=return_value,
            metadata={"belgie": True, "code_language": "typescript"},
        )

    async def _enter_environment(self, stack: AsyncExitStack) -> BelgieEnvironment:
        if self.environment is None:
            return await stack.enter_async_context(Environment())
        if isinstance(self.environment, Environment):
            return await stack.enter_async_context(self.environment)
        return self.environment

    async def _run_script(self, source: str) -> JsonOutput:
        script = Script(source)
        if self._active_runtime is not None:
            runner = self._active_runtime(script)
            return await runner()

        active_environment = self._active_environment
        if active_environment is None:
            raise UserError(TOOLSET_NOT_ENTERED_MESSAGE)

        options = self.runtime_options or DEFAULT_RUNTIME_OPTIONS
        async with Runtime(env=active_environment, options=options) as active_runtime:
            runner = active_runtime(script)
            return await runner()

    def _resolved_description(self) -> str:
        if self.dangerously_replace_instructions is not None:
            return self.dangerously_replace_instructions
        if self.instructions is None:
            return RUN_CODE_DESCRIPTION
        return f"{RUN_CODE_DESCRIPTION}\n\n{self.instructions}"
