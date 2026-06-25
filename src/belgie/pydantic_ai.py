from __future__ import annotations

import asyncio
import inspect
import json
import re
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field, replace
from typing import TYPE_CHECKING, Annotated, Any, Final, NotRequired, TypedDict, cast

from pydantic import Field, TypeAdapter, ValidationError
from pydantic_ai import AbstractToolset, ToolDefinition, WrapperToolset
from pydantic_ai.capabilities import AbstractCapability, CapabilityOrdering
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred, ModelRetry, UserError
from pydantic_ai.messages import (
    InstructionPart,
    ToolCallPart,
    ToolReturn,
    ToolReturnContent,
    ToolReturnPart,
    is_multi_modal_content,
)
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.tools import AgentDepsT, RunContext, ToolDenied, ToolSelector, matches_tool_selector
from pydantic_ai.toolsets.abstract import SchemaValidatorProt, ToolsetTool

from belgie import Environment, Runtime, Script
from belgie.errors import BelgieJavaScriptError, BelgieModuleError, BelgieRuntimeError

if TYPE_CHECKING:
    from os import PathLike

ToolSearchCapability: type[AbstractCapability[Any]] | None
try:
    from pydantic_ai.capabilities._tool_search import ToolSearch as ImportedToolSearchCapability
except ImportError:  # pragma: no cover
    ToolSearchCapability = None
else:
    ToolSearchCapability = ImportedToolSearchCapability

RUN_JAVASCRIPT_TOOL_NAME: Final[str] = "run_javascript"
DEFAULT_MAX_TOOL_ROUNDS: Final[int] = 8
TOOL_SEARCH_NAME: Final[str] = "search_tools"
INSTRUCTION_MODE_CONFLICT_MESSAGE: Final[str] = (
    "`instructions` and `dangerously_replace_instructions` are mutually exclusive."
)
MAX_TOOL_ROUNDS_MESSAGE: Final[str] = "`max_tool_rounds` must be greater than zero."
CTX_TOOL_MANAGER_REQUIRED_MESSAGE: Final[str] = "JavaScriptCodeModeToolset requires `ctx.tool_manager` to be set."
NONDETERMINISTIC_TOOL_CALLS_MESSAGE: Final[str] = (
    "JavaScript tool calls changed between replay rounds; keep tool arguments deterministic."
)
UNAWAITED_TOOL_CALL_MESSAGE: Final[str] = "JavaScript started tool calls that were not awaited."
NO_PENDING_TOOL_CALLS_MESSAGE: Final[str] = "JavaScript reported pending tool execution without any tool calls."
UNEXPECTED_REPLAY_END_MESSAGE: Final[str] = "JavaScript replay ended unexpectedly."
INVALID_INTERNAL_RESPONSE_MESSAGE: Final[str] = "JavaScript code mode returned an invalid internal response."
INVALID_INTERNAL_STATUS_MESSAGE: Final[str] = "JavaScript code mode returned an invalid internal status."
INVALID_INTERNAL_CALL_COUNT_MESSAGE: Final[str] = "JavaScript code mode returned an invalid internal call count."
INVALID_PENDING_TOOL_CALL_MESSAGE: Final[str] = "JavaScript code mode returned an invalid pending tool call."
INVALID_IDENT_CHARS: Final[re.Pattern[str]] = re.compile(r"[^a-zA-Z0-9_$]")
PRIMITIVE_TYPESCRIPT_TYPES: Final[dict[str, str]] = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}
JS_RESERVED_WORDS: Final[frozenset[str]] = frozenset(
    {
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "import",
        "in",
        "instanceof",
        "new",
        "null",
        "return",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
    },
)

BASE_RUN_JAVASCRIPT_INSTRUCTIONS: Final[str] = """\
Write and run JavaScript in a Belgie sandbox.

The code is an async JavaScript function body:
- Use `return` to produce the final value.
- Use `await import("pkg")` for package imports inside the snippet.
- Return JSON-safe values only: objects, arrays, strings, numbers, booleans, or null.
- Tool functions are already in scope. Call them with one object argument, for example
  `await search({ query: "belgie" })`.
- Use deterministic tool arguments. Randomness, clocks, or external side effects can make replay fail.

The final returned value is passed through directly. If `console.log()` was called, the tool returns
`{"output": "...", "result": ...}` instead.\
"""

SEARCH_TOOLS_MODIFIER: Final[str] = " Discovered tools become callable inside `run_javascript` on later invocations."
TOOL_SEARCH_ADDENDUM: Final[str] = (
    f"\n\nNot all functions may be available initially. Use `{TOOL_SEARCH_NAME}` to discover additional functions"
    f" that will become callable inside `{RUN_JAVASCRIPT_TOOL_NAME}` on subsequent invocations."
)
TOOL_RETURN_CONTENT_ADAPTER: Final[TypeAdapter[Any]] = TypeAdapter(ToolReturnContent)


class RunJavaScriptArguments(TypedDict):
    code: Annotated[str, Field(description="The JavaScript async function body to execute in Belgie.")]


RUN_JAVASCRIPT_ADAPTER: Final[TypeAdapter[RunJavaScriptArguments]] = TypeAdapter(RunJavaScriptArguments)
RUN_JAVASCRIPT_JSON_SCHEMA: Final[dict[str, Any]] = RUN_JAVASCRIPT_ADAPTER.json_schema()
RUN_JAVASCRIPT_ARGS_VALIDATOR: Final[SchemaValidatorProt] = cast(
    "SchemaValidatorProt",
    RUN_JAVASCRIPT_ADAPTER.validator,
)


class ToolCallResult(TypedDict):
    key: str
    ok: bool
    value: NotRequired[Any]
    error: NotRequired[str]


@dataclass(frozen=True, kw_only=True)
class PendingToolCall:
    name: str
    original_name: str
    args: dict[str, Any]
    key: str
    index: int


@dataclass(kw_only=True)
class RunJavaScriptTool(ToolsetTool[AgentDepsT]):
    callable_defs: dict[str, ToolDefinition]
    sanitized_to_original: dict[str, str]
    wrapped_tools: dict[str, ToolsetTool[AgentDepsT]]


@dataclass(kw_only=True)
class DispatchState[AgentDepsT]:
    ctx: RunContext[AgentDepsT]
    tool_manager: ToolManager[AgentDepsT]
    nested_calls: dict[str, ToolCallPart]
    nested_returns: dict[str, ToolReturnPart]
    call_counter: int = 0


@dataclass
class JavaScriptCodeMode(AbstractCapability[AgentDepsT]):
    tools: ToolSelector[AgentDepsT] = field(default="all")
    max_retries: int = 3

    _: KW_ONLY

    dependencies: Mapping[str, str] | None = None
    path: str | PathLike[str] | None = None
    lockfile: str | PathLike[str] | None = None
    cache: str | PathLike[str] | None = None
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    dynamic_catalog: bool = False
    instructions: str | None = None
    dangerously_replace_instructions: str | None = None

    def __post_init__(self) -> None:
        if self.instructions is not None and self.dangerously_replace_instructions is not None:
            raise UserError(INSTRUCTION_MODE_CONFLICT_MESSAGE)
        if self.max_tool_rounds < 1:
            raise UserError(MAX_TOOL_ROUNDS_MESSAGE)

    def get_ordering(self) -> CapabilityOrdering:
        if ToolSearchCapability is None:
            return CapabilityOrdering(position="outermost")
        return CapabilityOrdering(position="outermost", wraps=[ToolSearchCapability])

    async def for_run(self, ctx: RunContext[AgentDepsT]) -> JavaScriptCodeMode[AgentDepsT]:
        del ctx
        if self.dynamic_catalog:
            return replace(self)
        return self

    def get_wrapper_toolset(self, toolset: AbstractToolset[AgentDepsT]) -> AbstractToolset[AgentDepsT] | None:
        return JavaScriptCodeModeToolset(
            wrapped=toolset,
            tool_selector=self.tools,
            max_retries=self.max_retries,
            dependencies=self.dependencies,
            path=self.path,
            lockfile=self.lockfile,
            cache=self.cache,
            max_tool_rounds=self.max_tool_rounds,
            dynamic_catalog=self.dynamic_catalog,
            instructions=self.instructions,
            dangerously_replace_instructions=self.dangerously_replace_instructions,
        )


@dataclass
class JavaScriptCodeModeToolset(WrapperToolset[AgentDepsT]):
    tool_selector: ToolSelector[AgentDepsT] = "all"
    max_retries: int = 3
    dependencies: Mapping[str, str] | None = None
    path: str | PathLike[str] | None = None
    lockfile: str | PathLike[str] | None = None
    cache: str | PathLike[str] | None = None
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    dynamic_catalog: bool = False
    instructions: str | None = None
    dangerously_replace_instructions: str | None = None
    last_catalog: str = field(default="", init=False, repr=False)
    warned_return_schemas: set[str] = field(default_factory=set[str], init=False, repr=False)

    async def for_run(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:
        wrapped = await self.wrapped.for_run(ctx)
        return replace(self, wrapped=wrapped)

    async def for_run_step(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:
        wrapped = await self.wrapped.for_run_step(ctx)
        if wrapped is self.wrapped:
            return self
        new_self = replace(self, wrapped=wrapped)
        new_self.last_catalog = self.last_catalog
        new_self.warned_return_schemas = self.warned_return_schemas
        return new_self

    async def get_instructions(
        self,
        ctx: RunContext[AgentDepsT],
    ) -> str | InstructionPart | Sequence[str | InstructionPart] | None:
        upstream = await self.wrapped.get_instructions(ctx)
        if not self.last_catalog:
            return upstream
        catalog = InstructionPart(content=self.last_catalog, dynamic=True)
        if upstream is None:
            return catalog
        if isinstance(upstream, (str, InstructionPart)):
            return [upstream, catalog]
        return [*upstream, catalog]

    async def get_tools(self, ctx: RunContext[AgentDepsT]) -> dict[str, ToolsetTool[AgentDepsT]]:
        wrapped_tools = await self.wrapped.get_tools(ctx)
        sandboxed_tools: dict[str, ToolsetTool[AgentDepsT]] = {}
        native_tools: dict[str, ToolsetTool[AgentDepsT]] = {}

        for name, tool in wrapped_tools.items():
            if tool.tool_def.tool_kind is not None or tool.tool_def.defer_loading or tool.tool_def.unless_native:
                native_tools[name] = tool
            elif await matches_tool_selector(self.tool_selector, ctx, tool.tool_def):
                sandboxed_tools[name] = tool
            else:
                native_tools[name] = tool

        callable_defs, sanitized_to_original = self._partition_callable_tools(sandboxed_tools)
        if self.dynamic_catalog:
            description = self._resolved_base()
            self.last_catalog = self._render_catalog(callable_defs, sanitized_to_original)
        else:
            description = self._build_description(callable_defs, sanitized_to_original)
            self.last_catalog = ""

        if RUN_JAVASCRIPT_TOOL_NAME in native_tools:
            message = f"Tool name {RUN_JAVASCRIPT_TOOL_NAME!r} is reserved for JavaScript code mode."
            raise UserError(message)

        if TOOL_SEARCH_NAME in native_tools:
            search_tool = native_tools[TOOL_SEARCH_NAME]
            native_tools[TOOL_SEARCH_NAME] = replace(
                search_tool,
                tool_def=replace(
                    search_tool.tool_def,
                    description=(search_tool.tool_def.description or "") + SEARCH_TOOLS_MODIFIER,
                ),
            )
            description += TOOL_SEARCH_ADDENDUM

        result: dict[str, ToolsetTool[AgentDepsT]] = dict(native_tools)
        result[RUN_JAVASCRIPT_TOOL_NAME] = RunJavaScriptTool(
            toolset=self,
            tool_def=ToolDefinition(
                name=RUN_JAVASCRIPT_TOOL_NAME,
                description=description,
                parameters_json_schema=RUN_JAVASCRIPT_JSON_SCHEMA,
                metadata={"code_arg_name": "code", "code_arg_language": "javascript"},
                sequential=True,
            ),
            max_retries=self.max_retries,
            args_validator=RUN_JAVASCRIPT_ARGS_VALIDATOR,
            callable_defs=callable_defs,
            sanitized_to_original=sanitized_to_original,
            wrapped_tools=wrapped_tools,
        )
        return result

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDepsT],
        tool: ToolsetTool[AgentDepsT],
    ) -> object:
        if not isinstance(tool, RunJavaScriptTool):
            return await self.wrapped.call_tool(name, tool_args, ctx, tool)
        return await self._run_javascript(tool_args["code"], ctx, tool)

    async def _run_javascript(
        self,
        code: str,
        ctx: RunContext[AgentDepsT],
        tool: RunJavaScriptTool[AgentDepsT],
    ) -> ToolReturn[object]:
        parent_manager = ctx.tool_manager
        if parent_manager is None:
            raise UserError(CTX_TOOL_MANAGER_REQUIRED_MESSAGE)

        dispatch_state = DispatchState(
            ctx=ctx,
            tool_manager=ToolManager(
                toolset=self.wrapped,
                root_capability=parent_manager.root_capability,
                ctx=ctx,
                tools=tool.wrapped_tools,
                default_max_retries=parent_manager.default_max_retries,
            ),
            nested_calls={},
            nested_returns={},
        )
        results: list[ToolCallResult] = []

        for round_number in range(self.max_tool_rounds + 1):
            response = await self._execute_replay(code, tool.callable_defs, results)
            status = _response_status(response)
            output = _response_output(response)
            call_count = _response_call_count(response)
            if call_count < len(results):
                raise ModelRetry(NONDETERMINISTIC_TOOL_CALLS_MESSAGE)
            if status == "complete":
                if call_count > len(results):
                    raise ModelRetry(UNAWAITED_TOOL_CALL_MESSAGE)
                result = response.get("result")
                return _build_tool_return(
                    result,
                    output,
                    dispatch_state.nested_calls,
                    dispatch_state.nested_returns,
                )
            if round_number == self.max_tool_rounds:
                message = f"JavaScript requested tools for more than {self.max_tool_rounds} replay rounds."
                raise ModelRetry(message)

            pending = _response_pending_calls(response, tool.sanitized_to_original)
            if not pending:
                raise ModelRetry(NO_PENDING_TOOL_CALLS_MESSAGE)
            if any(call.index < len(results) for call in pending):
                raise ModelRetry(NONDETERMINISTIC_TOOL_CALLS_MESSAGE)

            if _must_dispatch_sequentially(pending, tool.callable_defs, dispatch_state.tool_manager):
                results.extend([await self._dispatch_pending(call, dispatch_state) for call in pending])
            else:
                results.extend(
                    await asyncio.gather(*(self._dispatch_pending(call, dispatch_state) for call in pending)),
                )

        raise ModelRetry(UNEXPECTED_REPLAY_END_MESSAGE)

    async def _dispatch_pending(
        self,
        call: PendingToolCall,
        state: DispatchState[AgentDepsT],
    ) -> ToolCallResult:
        state.call_counter += 1
        tool_call_id = f"{state.ctx.tool_call_id or 'pyd_ai_js_code_mode'}__{state.call_counter}"
        call_part = ToolCallPart(tool_name=call.original_name, args=call.args, tool_call_id=tool_call_id)
        state.nested_calls[tool_call_id] = call_part
        try:
            result = await state.tool_manager.handle_call(call_part, wrap_validation_errors=False)
        except ValidationError as exc:
            message = f"Tool {call.original_name!r} argument validation failed:\n{exc}"
            raise ModelRetry(message) from exc
        except (CallDeferred, ApprovalRequired) as exc:
            message = (
                f"Tool {call.original_name!r} raised {type(exc).__name__} inside JavaScript code mode, "
                "but no deferred-tool handler resolved it."
            )
            raise UserError(message) from exc

        if isinstance(result, ToolDenied):
            state.nested_returns[tool_call_id] = ToolReturnPart(
                tool_name=call.original_name,
                content=result.message,
                tool_call_id=tool_call_id,
                outcome="denied",
            )
            message = f"Tool {call.original_name!r} call denied: {result.message}"
            raise ModelRetry(message)

        return_metadata: object = None
        if isinstance(result, ToolReturn):
            return_metadata = result.metadata
            result = result.return_value

        state.nested_returns[tool_call_id] = ToolReturnPart(
            tool_name=call.original_name,
            content=result,
            tool_call_id=tool_call_id,
            metadata=return_metadata,
        )
        value = TOOL_RETURN_CONTENT_ADAPTER.dump_python(result, mode="json")
        return {"key": call.key, "ok": True, "value": value}

    async def _execute_replay(
        self,
        code: str,
        callable_defs: dict[str, ToolDefinition],
        results: list[ToolCallResult],
    ) -> dict[str, Any]:
        script = Script(_build_replay_script(code, callable_defs))
        payload = {"results": results}
        try:
            if self._uses_environment():
                environment = Environment(
                    self.dependencies,
                    path=self.path,
                    lockfile=self.lockfile,
                    cache=self.cache,
                )
                async with environment as env:
                    if self.dependencies is not None:
                        await env.install()
                    async with Runtime(env=env) as runtime:
                        result = await runtime(script)(payload)
            else:
                async with Runtime() as runtime:
                    result = await runtime(script)(payload)
        except BelgieJavaScriptError as exc:
            if "BelgieCodeModePendingToolCall" in str(exc):
                raise ModelRetry(UNAWAITED_TOOL_CALL_MESSAGE) from exc
            message = f"JavaScript runtime error:\n{exc}"
            raise ModelRetry(message) from exc
        except BelgieModuleError as exc:
            message = f"JavaScript module error:\n{exc}"
            raise ModelRetry(message) from exc
        except BelgieRuntimeError as exc:
            message = f"Belgie runtime error:\n{exc}"
            raise ModelRetry(message) from exc

        if not isinstance(result, dict):
            raise ModelRetry(INVALID_INTERNAL_RESPONSE_MESSAGE)
        return result

    def _uses_environment(self) -> bool:
        return any(item is not None for item in (self.dependencies, self.path, self.lockfile, self.cache))

    def _partition_callable_tools(
        self,
        wrapped_tools: dict[str, ToolsetTool[AgentDepsT]],
    ) -> tuple[dict[str, ToolDefinition], dict[str, str]]:
        callable_defs: dict[str, ToolDefinition] = {}
        sanitized_to_original: dict[str, str] = {}
        for name, tool in wrapped_tools.items():
            tool_def = tool.tool_def
            safe_name = _sanitize_tool_name(name)
            if safe_name == RUN_JAVASCRIPT_TOOL_NAME:
                message = f"Tool name {name!r} is reserved for the JavaScript code mode meta-tool after sanitization."
                raise UserError(message)
            if safe_name in callable_defs:
                existing = sanitized_to_original.get(safe_name, safe_name)
                warnings.warn(
                    f"JavaScriptCodeMode: tool {name!r} (sanitized to {safe_name!r}) collides with "
                    f"{existing!r}; {name!r} will be hidden from the sandbox.",
                    UserWarning,
                    stacklevel=2,
                )
                continue
            if tool_def.return_schema is None and name not in self.warned_return_schemas:
                self.warned_return_schemas.add(name)
                warnings.warn(
                    f"JavaScriptCodeMode: tool {name!r} has no return schema; "
                    "its generated TypeScript signature will return unknown.",
                    UserWarning,
                    stacklevel=2,
                )
            if safe_name != name:
                sanitized_to_original[safe_name] = name
                tool_def = replace(tool_def, name=safe_name)
            callable_defs[safe_name] = tool_def
        return callable_defs, sanitized_to_original

    def _resolved_base(self) -> str:
        if self.dangerously_replace_instructions is not None:
            return self.dangerously_replace_instructions
        base = default_run_javascript_instructions()
        if self.instructions is None:
            return base
        return f"{base}\n\n{self.instructions}"

    def _build_description(
        self,
        callable_defs: dict[str, ToolDefinition],
        sanitized_to_original: dict[str, str],
    ) -> str:
        catalog = self._render_catalog(callable_defs, sanitized_to_original)
        if not catalog:
            return self._resolved_base()
        return f"{self._resolved_base()}\n\n{catalog}"

    @staticmethod
    def _render_catalog(
        callable_defs: dict[str, ToolDefinition],
        sanitized_to_original: dict[str, str],
    ) -> str:
        if not callable_defs:
            return ""
        sections = [
            "The following async functions are available inside the JavaScript sandbox. "
            "Call them with one object argument and `await` the result.",
            "```ts\n"
            + "\n\n".join(_render_tool_signature(td, sanitized_to_original) for td in callable_defs.values())
            + "\n```",
        ]
        return "\n\n".join(sections)


def default_run_javascript_instructions() -> str:
    return BASE_RUN_JAVASCRIPT_INSTRUCTIONS


def _sanitize_tool_name(name: str) -> str:
    sanitized = INVALID_IDENT_CHARS.sub("_", name)
    if not sanitized or not re.match(r"^[A-Za-z_$]", sanitized):
        sanitized = f"_{sanitized}"
    if sanitized in JS_RESERVED_WORDS:
        sanitized = f"{sanitized}_"
    return sanitized


def _render_tool_signature(tool_def: ToolDefinition, sanitized_to_original: dict[str, str]) -> str:
    params = _schema_to_typescript(tool_def.parameters_json_schema)
    returns = _schema_to_typescript(tool_def.return_schema) if tool_def.return_schema is not None else "unknown"
    original = sanitized_to_original.get(tool_def.name)
    alias = f"\n// Original tool name: {original}" if original is not None else ""
    description = f"// {tool_def.description}\n" if tool_def.description else ""
    return f"{description}async function {tool_def.name}(args: {params}): Promise<{returns}>;{alias}"


def _schema_to_typescript(schema: Mapping[str, Any] | None) -> str:
    if not schema:
        return "unknown"
    combined = _combined_schema_to_typescript(schema)
    if combined is not None:
        return combined
    enum = _enum_schema_to_typescript(schema)
    if enum is not None:
        return enum
    return _typed_schema_to_typescript(schema)


def _combined_schema_to_typescript(schema: Mapping[str, Any]) -> str | None:
    if "anyOf" in schema:
        return " | ".join(_schema_to_typescript(item) for item in _schema_list(schema["anyOf"])) or "unknown"
    if "oneOf" in schema:
        return " | ".join(_schema_to_typescript(item) for item in _schema_list(schema["oneOf"])) or "unknown"
    return None


def _enum_schema_to_typescript(schema: Mapping[str, Any]) -> str | None:
    if "enum" in schema and isinstance(schema["enum"], list):
        return " | ".join(json.dumps(item) for item in schema["enum"])
    return None


def _typed_schema_to_typescript(schema: Mapping[str, Any]) -> str:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " | ".join(_schema_to_typescript({**schema, "type": item}) for item in schema_type)
    if isinstance(schema_type, str) and schema_type in PRIMITIVE_TYPESCRIPT_TYPES:
        return PRIMITIVE_TYPESCRIPT_TYPES[schema_type]
    if schema_type == "array":
        items = schema.get("items")
        return f"Array<{_schema_to_typescript(items if isinstance(items, Mapping) else None)}>"
    if schema_type == "object" or "properties" in schema:
        return _object_schema_to_typescript(schema)
    return "unknown"


def _schema_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast("Mapping[str, Any]", item) for item in value if isinstance(item, Mapping)]


def _object_schema_to_typescript(schema: Mapping[str, Any]) -> str:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        return "Record<string, unknown>"
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    fields: list[str] = []
    for name, subschema in properties.items():
        optional = "" if name in required_names else "?"
        field_type = _schema_to_typescript(subschema if isinstance(subschema, Mapping) else None)
        fields.append(f"{json.dumps(name)}{optional}: {field_type}")
    return "{ " + "; ".join(fields) + " }"


def _build_replay_script(code: str, callable_defs: dict[str, ToolDefinition]) -> str:
    bindings = "\n".join(
        f"  const {name} = async (args = {{}}) => __callTool({json.dumps(name)}, args);" for name in callable_defs
    )
    return f"""\
export default async function run(input) {{
  const __logs = [];
  const console = {{
    ...globalThis.console,
    log: (...values) => {{
      __logs.push(values.map((value) => __formatLog(value)).join(" "));
    }},
  }};
  const __results = new Map((input.results ?? []).map((item) => [item.key, item]));
  const __calls = [];
  let __callIndex = 0;

  function __formatLog(value) {{
    if (typeof value === "string") {{
      return value;
    }}
    try {{
      return JSON.stringify(value);
    }} catch {{
      return String(value);
    }}
  }}

  function __stable(value) {{
    if (Array.isArray(value)) {{
      return value.map((item) => __stable(item));
    }}
    if (value && typeof value === "object" && value.constructor === Object) {{
      const output = {{}};
      for (const key of Object.keys(value).sort()) {{
        output[key] = __stable(value[key]);
      }}
      return output;
    }}
    return value;
  }}

  function __stableStringify(value) {{
    return JSON.stringify(__stable(value));
  }}

  async function __callTool(name, args = {{}}) {{
    if (args === undefined || args === null) {{
      args = {{}};
    }}
    if (typeof args !== "object" || Array.isArray(args)) {{
      throw new TypeError(`${{name}} expects one object argument.`);
    }}
    const index = __callIndex++;
    const key = `${{index}}:${{name}}:${{__stableStringify(args)}}`;
    if (__results.has(key)) {{
      const result = __results.get(key);
      if (result.ok) {{
        return result.value ?? null;
      }}
      throw new Error(result.error ?? `${{name}} failed`);
    }}
    __calls.push({{ name, args, key, index }});
    throw new Error(`BelgieCodeModePendingToolCall:${{key}}`);
  }}

{bindings}

  async function __belgieUserMain() {{
{_indent_user_code(code)}
  }}

  try {{
    const result = await __belgieUserMain();
    return {{
      status: "complete",
      result: result ?? null,
      output: __logs.join("\\n"),
      callCount: __callIndex,
    }};
  }} catch (error) {{
    if (__calls.length > 0) {{
      return {{
        status: "pending",
        calls: __calls,
        output: __logs.join("\\n"),
        callCount: __callIndex,
      }};
    }}
    throw error;
  }}
}}
"""


def _indent_user_code(code: str) -> str:
    return "\n".join(f"    {line}" if line else "" for line in code.splitlines())


def _response_status(response: Mapping[str, Any]) -> str:
    status = response.get("status")
    if status not in {"complete", "pending"}:
        raise ModelRetry(INVALID_INTERNAL_STATUS_MESSAGE)
    return status


def _response_output(response: Mapping[str, Any]) -> str:
    output = response.get("output", "")
    return output if isinstance(output, str) else ""


def _response_call_count(response: Mapping[str, Any]) -> int:
    call_count = response.get("callCount", 0)
    if not isinstance(call_count, int):
        raise ModelRetry(INVALID_INTERNAL_CALL_COUNT_MESSAGE)
    return call_count


def _response_pending_calls(
    response: Mapping[str, Any],
    sanitized_to_original: dict[str, str],
) -> list[PendingToolCall]:
    raw_calls = response.get("calls")
    if not isinstance(raw_calls, list):
        return []

    calls: list[PendingToolCall] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ModelRetry(INVALID_PENDING_TOOL_CALL_MESSAGE)
        name = raw_call.get("name")
        args = raw_call.get("args")
        key = raw_call.get("key")
        index = raw_call.get("index")
        if (
            not isinstance(name, str)
            or not isinstance(args, dict)
            or not isinstance(key, str)
            or not isinstance(index, int)
        ):
            raise ModelRetry(INVALID_PENDING_TOOL_CALL_MESSAGE)
        calls.append(
            PendingToolCall(
                name=name,
                original_name=sanitized_to_original.get(name, name),
                args=args,
                key=key,
                index=index,
            ),
        )
    return calls


def _must_dispatch_sequentially(
    calls: Sequence[PendingToolCall],
    callable_defs: dict[str, ToolDefinition],
    tool_manager: ToolManager[Any],
) -> bool:
    if _global_mode_is_sequential(tool_manager.get_parallel_execution_mode):
        return True
    return any(callable_defs[call.name].sequential for call in calls)


def _global_mode_is_sequential(get_mode: Callable[..., str]) -> bool:
    if inspect.signature(get_mode).parameters:
        return get_mode([]) != "parallel"
    return get_mode() != "parallel"


def _build_tool_return(
    result: object,
    output: str,
    nested_calls: dict[str, ToolCallPart],
    nested_returns: dict[str, ToolReturnPart],
) -> ToolReturn[object]:
    if result is not None:
        result = TOOL_RETURN_CONTENT_ADAPTER.validate_python(result)

    if not output:
        return_value: Any = result if result is not None else {}
    elif result is None:
        return_value = {"output": output}
    elif _contains_multimodal(result):
        return_value = [output, *result] if isinstance(result, list) else [output, result]
    else:
        return_value = {"output": output, "result": result}

    return ToolReturn(
        return_value=return_value,
        metadata={
            "code_mode": True,
            "code_language": "javascript",
            "tool_calls": nested_calls,
            "tool_returns": nested_returns,
        },
    )


def _contains_multimodal(value: object) -> bool:
    if is_multi_modal_content(value):
        return True
    if isinstance(value, list):
        return any(is_multi_modal_content(item) for item in value)
    return False


__all__: tuple[str, ...] = (
    "JavaScriptCodeMode",
    "JavaScriptCodeModeToolset",
    "default_run_javascript_instructions",
)
