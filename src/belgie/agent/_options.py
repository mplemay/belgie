from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypedDict

from belgie._core import AsyncEnvironment, Environment, SyncEnvironment

if TYPE_CHECKING:
    from belgie import Runtime, RuntimeOptions

type BelgieEnvironment = Environment | SyncEnvironment | AsyncEnvironment

INSTRUCTIONS_CONFLICT_MESSAGE: Final[str] = (
    "`instructions` and `dangerously_replace_instructions` are mutually exclusive: "
    "`instructions` appends to the built-in prose, while "
    "`dangerously_replace_instructions` replaces it."
)
RUNTIME_ENVIRONMENT_CONFLICT_MESSAGE: Final[str] = (
    "`runtime` cannot be combined with `environment` or `runtime_options`."
)
DEFER_LOADING_REQUIRES_ID_MESSAGE: Final[str] = "`defer_loading=True` requires a stable `id` on the Belgie capability."
PLUGINS_REQUIRE_RENDERING_MESSAGE: Final[str] = "`plugins` requires `enable_rendering=True`."
INVALID_PLUGINS_MESSAGE: Final[str] = "plugins must be a sequence of non-empty strings."


class BelgieOptionsKwargs(TypedDict):
    max_retries: int
    runtime: Runtime | None
    environment: BelgieEnvironment | None
    runtime_options: RuntimeOptions | None
    instructions: str | None
    dangerously_replace_instructions: str | None
    timeout: float | None
    defer_loading: bool
    capability_id: str | None
    enable_rendering: bool
    plugins: tuple[str, ...]


@dataclass(kw_only=True)
class BelgieOptions:
    max_retries: int = 3
    runtime: Runtime | None = None
    environment: BelgieEnvironment | None = None
    runtime_options: RuntimeOptions | None = None
    instructions: str | None = None
    dangerously_replace_instructions: str | None = None
    timeout: float | None = None
    defer_loading: bool = False
    capability_id: str | None = None
    enable_rendering: bool = True
    plugins: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.instructions is not None and self.dangerously_replace_instructions is not None:
            raise ValueError(INSTRUCTIONS_CONFLICT_MESSAGE)
        if self.runtime is not None and (self.environment is not None or self.runtime_options is not None):
            raise ValueError(RUNTIME_ENVIRONMENT_CONFLICT_MESSAGE)
        if self.defer_loading and self.capability_id is None:
            raise ValueError(DEFER_LOADING_REQUIRES_ID_MESSAGE)
        if type(self.enable_rendering) is not bool:
            message = f"enable_rendering must be a bool, got {self.enable_rendering!r}."
            raise ValueError(message)
        if isinstance(self.plugins, (str, bytes)) or not isinstance(self.plugins, Sequence):
            raise TypeError(INVALID_PLUGINS_MESSAGE)
        validated: list[str] = []
        for plugin in self.plugins:
            if type(plugin) is not str or not plugin:
                raise ValueError(INVALID_PLUGINS_MESSAGE)
            validated.append(plugin)
        self.plugins = tuple(validated)
        if self.plugins and not self.enable_rendering:
            raise ValueError(PLUGINS_REQUIRE_RENDERING_MESSAGE)

    def options_kwargs(self) -> BelgieOptionsKwargs:
        return {
            "max_retries": self.max_retries,
            "runtime": self.runtime,
            "environment": self.environment,
            "runtime_options": self.runtime_options,
            "instructions": self.instructions,
            "dangerously_replace_instructions": self.dangerously_replace_instructions,
            "timeout": self.timeout,
            "defer_loading": self.defer_loading,
            "capability_id": self.capability_id,
            "enable_rendering": self.enable_rendering,
            "plugins": self.plugins,
        }
