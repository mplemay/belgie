from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Self, TypeVar

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.durable_exec._base import BaseDurabilityCapability
from pydantic_ai.exceptions import UserError
from pydantic_ai.tools import AgentDepsT

from belgie.pydantic_ai._session import (
    DEFAULT_MAX_OLD_GENERATION_SIZE_MB,
    DEFAULT_TIMEOUT,
    BelgieSandboxSession,
    _validate_plugins,
)
from belgie.pydantic_ai._toolset import DEFAULT_MAX_OUTPUT_BYTES, BelgieSandboxToolset

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.agent.abstract import AbstractAgent

    _AgentOutputT = TypeVar("_AgentOutputT")

DEFAULT_CAPABILITY_ID: Final[str] = "belgie_sandbox"
DEFAULT_CAPABILITY_DESCRIPTION: Final[str] = (
    "Run JavaScript, TypeScript, or TSX modules in a restricted embedded Deno sandbox via `run_typescript`."
)


def _validate_bool(name: str, value: object) -> None:
    if type(value) is not bool:
        message = f"{name} must be a bool, got {value!r}."
        raise ValueError(message)


def _validate_int(name: str, value: object, *, minimum: int, allow_none: bool = False) -> None:
    if allow_none and value is None:
        return
    if type(value) is not int or value < minimum:
        qualifier = "non-negative" if minimum == 0 else "positive"
        optional = " or None" if allow_none else ""
        message = f"{name} must be a {qualifier} integer{optional}, got {value!r}."
        raise ValueError(message)


def _validate_configuration(capability: BelgieSandbox[Any]) -> None:
    for name, value in (
        ("allow_package_imports", capability.allow_package_imports),
        ("allow_network", capability.allow_network),
        ("enable_rendering", capability.enable_rendering),
    ):
        _validate_bool(name, value)
    plugins = _validate_plugins(capability.plugins)
    if plugins and not capability.enable_rendering:
        message = "plugins requires enable_rendering=True."
        raise ValueError(message)
    object.__setattr__(capability, "plugins", plugins)
    _validate_int(
        "max_old_generation_size_mb",
        capability.max_old_generation_size_mb,
        minimum=1,
        allow_none=True,
    )
    if type(capability.timeout) is bool or not math.isfinite(capability.timeout) or capability.timeout <= 0:
        message = f"timeout must be a positive finite number, got {capability.timeout!r}."
        raise ValueError(message)
    _validate_int("max_output_bytes", capability.max_output_bytes, minimum=1)
    _validate_int("max_retries", capability.max_retries, minimum=0)
    if capability.instructions is not None and type(capability.instructions) is not str:
        message = f"instructions must be a string or None, got {capability.instructions!r}."
        raise ValueError(message)
    if capability.session is not None:
        conflicts = [
            name
            for name, value, default in (
                ("allow_package_imports", capability.allow_package_imports, False),
                ("allow_network", capability.allow_network, False),
                ("enable_rendering", capability.enable_rendering, False),
                ("plugins", plugins, ()),
                (
                    "max_old_generation_size_mb",
                    capability.max_old_generation_size_mb,
                    DEFAULT_MAX_OLD_GENERATION_SIZE_MB,
                ),
            )
            if value != default
        ]
        if conflicts:
            message = (
                f"{', '.join(conflicts)} cannot be combined with `session`, which already owns "
                "the Belgie runtime configuration."
            )
            raise ValueError(message)


@dataclass(kw_only=True)
class BelgieSandbox(AbstractCapability[AgentDepsT]):
    allow_package_imports: bool = False
    allow_network: bool = False
    enable_rendering: bool = False
    plugins: Sequence[str] = ()
    max_old_generation_size_mb: int | None = DEFAULT_MAX_OLD_GENERATION_SIZE_MB
    timeout: float = DEFAULT_TIMEOUT
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    max_retries: int = 3
    session: BelgieSandboxSession | None = None
    instructions: str | None = None

    def __post_init__(self) -> None:
        _validate_configuration(self)
        if self.defer_loading and self.id is None:
            self.id = DEFAULT_CAPABILITY_ID
        if self.defer_loading and self.description is None:
            self.description = DEFAULT_CAPABILITY_DESCRIPTION

    def get_instructions(self) -> str | None:
        if self.instructions is not None:
            return self.instructions or None
        if self.session is not None:
            return (
                "Use `run_typescript` to execute complete JavaScript, TypeScript, or TSX modules in a "
                "caller-managed Belgie runtime. Export a default function or named `run` function and "
                "return JSON-serializable data. Runtime access and state lifetime depend on the supplied session."
            )
        if self.allow_package_imports:
            package_text = "npm, JSR, and URL imports are enabled"
        else:
            package_text = "npm, JSR, URL, and relative imports are disabled"
        network_text = "runtime network access is enabled" if self.allow_network else "runtime `fetch` is disabled"
        rendering_text = (
            "; use the `render_widget` tool with a default-export TSX module for inline React widgets"
            if self.enable_rendering
            else ""
        )
        return (
            "Use `run_typescript` to execute a complete JavaScript, TypeScript, or TSX module in a "
            "temporary Belgie Deno sandbox. Export a default function or named `run` function and return "
            f"JSON-serializable data. {package_text}; {network_text}{rendering_text}. Host files, environment "
            f"variables, subprocesses, FFI, and system information are unavailable to model scripts. Each call "
            f"has a {self.timeout:g}s deadline and a {self.max_output_bytes}-byte JSON output limit. The runtime "
            "is reset between agent runs."
        )

    def for_agent(self, agent: AbstractAgent[AgentDepsT, _AgentOutputT]) -> Self:
        durability: list[str] = []

        def collect(capability: AbstractCapability[AgentDepsT]) -> None:
            if isinstance(capability, BaseDurabilityCapability):
                durability.append(type(capability).__name__)

        agent.root_capability.apply(collect)
        if durability:
            names = ", ".join(sorted(durability))
            message = (
                f"BelgieSandbox does not support durable execution capabilities ({names}): "
                "its Deno runtime is live, process-local state that cannot cross activity, task, or replay boundaries."
            )
            raise UserError(message)
        return self

    def get_toolset(self) -> BelgieSandboxToolset[AgentDepsT]:
        return BelgieSandboxToolset[AgentDepsT](
            allow_package_imports=self.allow_package_imports,
            allow_network=self.allow_network,
            enable_rendering=self.enable_rendering,
            plugins=tuple(self.plugins),
            max_old_generation_size_mb=self.max_old_generation_size_mb,
            timeout=float(self.timeout),
            max_output_bytes=self.max_output_bytes,
            max_retries=self.max_retries,
            toolset_id=self.id or DEFAULT_CAPABILITY_ID,
            session=self.session,
        )
