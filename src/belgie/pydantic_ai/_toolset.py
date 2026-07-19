from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Self, cast

from pydantic_ai import AbstractToolset, RunContext, ToolDefinition, WrapperToolset
from pydantic_ai._deferred_capabilities import DEFERRED_CAPABILITY_TOOL_METADATA_KEY
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets._deferred_capability_loader import LOAD_CAPABILITY_TOOL_NAME
from pydantic_ai.toolsets.abstract import SchemaValidatorProt, ToolsetTool

from belgie.agent import (
    BUILD_WIDGET_JSON_SCHEMA,
    BUILD_WIDGET_METADATA,
    BUILD_WIDGET_TOOL_NAME,
    RUN_CODE_JSON_SCHEMA,
    RUN_CODE_METADATA,
    RUN_CODE_TOOL_NAME,
    BelgieOptions,
    BelgieRuntimeSession,
    BuildWidgetInput,
    RunCodeInput,
    format_script_failure,
    format_widget_failure,
    widget_build_summary,
)
from belgie.agent._build_widget import (
    BUILD_WIDGET_ARGS_VALIDATOR as _BUILD_WIDGET_ARGS_VALIDATOR,
    BUILD_WIDGET_DESCRIPTION,
)
from belgie.agent._run_code import (
    RUN_CODE_ARGS_VALIDATOR as _RUN_CODE_ARGS_VALIDATOR,
    resolved_description,
)
from belgie.errors import BelgieError
from belgie.widget import WidgetSource

if TYPE_CHECKING:
    from belgie.agent._runtime import AsyncExitArgs
    from belgie.widget._builder import _AsyncWidgetSession

RUN_CODE_ARGS_VALIDATOR: Final[SchemaValidatorProt] = cast(
    "SchemaValidatorProt",
    _RUN_CODE_ARGS_VALIDATOR,
)
BUILD_WIDGET_ARGS_VALIDATOR: Final[SchemaValidatorProt] = cast(
    "SchemaValidatorProt",
    _BUILD_WIDGET_ARGS_VALIDATOR,
)
UNSUPPORTED_TOOL_MESSAGE: Final[str] = "Belgie capability does not support the {requested_tool_name!r} tool."
TOOLSET_NOT_ENTERED_MESSAGE: Final[str] = "BelgieToolset must be entered before calling tools."


@dataclass(kw_only=True)
class _BelgieOptions(BelgieOptions):
    def validate(self) -> None:
        try:
            super().validate()
        except ValueError as error:
            raise UserError(str(error)) from error


@dataclass(kw_only=True)
class BelgieToolset(_BelgieOptions, WrapperToolset[AgentDepsT]):
    _exit_stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _session: BelgieRuntimeSession | None = field(default=None, init=False, repr=False)
    _widget_session: _AsyncWidgetSession | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.validate()

    async def for_run(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:
        new_wrapped = await self.wrapped.for_run(ctx)
        if new_wrapped is self.wrapped:
            return self
        return replace(self, wrapped=new_wrapped)

    async def for_run_step(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:
        new_wrapped = await self.wrapped.for_run_step(ctx)
        if new_wrapped is self.wrapped:
            return self
        return replace(self, wrapped=new_wrapped)

    async def get_instructions(self, ctx: RunContext[AgentDepsT]) -> None:  # noqa: ARG002
        # Wrapped toolset instructions must not leak into the system prompt.
        return None

    async def __aenter__(self) -> Self:
        if self._exit_stack is not None:
            return self

        stack = AsyncExitStack()
        try:
            await stack.enter_async_context(self.wrapped)
            session = BelgieRuntimeSession(**self.options_kwargs())
            await stack.enter_async_context(session)
            if self.widget_builder is not None:
                widget_session = self.widget_builder.new_async_session()
                await stack.enter_async_context(widget_session)
                self._widget_session = widget_session
            self._session = session
            self._exit_stack = stack
        except BaseException:
            await stack.aclose()
            raise
        return self

    async def __aexit__(self, *args: object) -> bool | None:
        stack = self._exit_stack
        self._exit_stack = None
        self._session = None
        self._widget_session = None
        if stack is None:
            return None
        return await stack.__aexit__(*cast("AsyncExitArgs", args))

    async def get_tools(self, ctx: RunContext[AgentDepsT]) -> dict[str, ToolsetTool[AgentDepsT]]:
        wrapped_tools = await self.wrapped.get_tools(ctx)
        tools = {name: tool for name, tool in wrapped_tools.items() if name == LOAD_CAPABILITY_TOOL_NAME}
        metadata: dict[str, Any] = dict(RUN_CODE_METADATA)
        if self.defer_loading:
            metadata[DEFERRED_CAPABILITY_TOOL_METADATA_KEY] = True
        tools[RUN_CODE_TOOL_NAME] = ToolsetTool(
            toolset=self,
            tool_def=ToolDefinition(
                name=RUN_CODE_TOOL_NAME,
                description=resolved_description(self),
                parameters_json_schema=RUN_CODE_JSON_SCHEMA,
                metadata=metadata,
                sequential=True,
                timeout=self.timeout,
                defer_loading=self.defer_loading,
                capability_id=self.capability_id if self.defer_loading else None,
            ),
            max_retries=self.max_retries,
            args_validator=RUN_CODE_ARGS_VALIDATOR,
        )
        if self.widget_builder is not None:
            widget_metadata: dict[str, Any] = dict(BUILD_WIDGET_METADATA)
            if self.defer_loading:
                widget_metadata[DEFERRED_CAPABILITY_TOOL_METADATA_KEY] = True
            tools[BUILD_WIDGET_TOOL_NAME] = ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name=BUILD_WIDGET_TOOL_NAME,
                    description=BUILD_WIDGET_DESCRIPTION,
                    parameters_json_schema=BUILD_WIDGET_JSON_SCHEMA,
                    metadata=widget_metadata,
                    sequential=True,
                    timeout=self.widget_builder.timeout,
                    defer_loading=self.defer_loading,
                    capability_id=self.capability_id if self.defer_loading else None,
                ),
                max_retries=self.max_retries,
                args_validator=BUILD_WIDGET_ARGS_VALIDATOR,
            )
        return tools

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDepsT],
        tool: ToolsetTool[AgentDepsT],
    ) -> Any:  # noqa: ANN401
        if name == LOAD_CAPABILITY_TOOL_NAME:
            return await self.wrapped.call_tool(name, tool_args, ctx, tool)
        if name == BUILD_WIDGET_TOOL_NAME:
            if self._widget_session is None:
                raise UserError(TOOLSET_NOT_ENTERED_MESSAGE)
            try:
                parsed = (
                    tool_args if isinstance(tool_args, BuildWidgetInput) else BuildWidgetInput.model_validate(tool_args)
                )
                source = WidgetSource(widget=parsed.widget, files=parsed.files)
                bundle = await self._widget_session.build(source)
            except (BelgieError, TimeoutError, ValueError) as error:
                raise ModelRetry(format_widget_failure(error)) from error
            return ToolReturn(
                return_value=widget_build_summary(bundle, parsed),
                metadata={"belgie": True, "widget": bundle},
            )
        if name != RUN_CODE_TOOL_NAME:
            raise UserError(
                UNSUPPORTED_TOOL_MESSAGE.format(
                    requested_tool_name=name,
                ),
            )
        if self._session is None:
            raise UserError(TOOLSET_NOT_ENTERED_MESSAGE)

        try:
            parsed = tool_args if isinstance(tool_args, RunCodeInput) else RunCodeInput.model_validate(tool_args)
            return_value = await self._session.run_script(parsed.code)
        except BelgieError as error:
            raise ModelRetry(format_script_failure(error)) from error
        except TimeoutError as error:
            raise ModelRetry(str(error)) from error

        return ToolReturn(
            return_value=return_value,
            metadata={"belgie": True, "code_language": RUN_CODE_METADATA["code_arg_language"]},
        )
