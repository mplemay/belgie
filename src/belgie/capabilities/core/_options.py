from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from belgie._core import AsyncEnvironment, Environment, SyncEnvironment

if TYPE_CHECKING:
    from belgie import Runtime, RuntimeOptions

type BelgieEnvironment = Environment | SyncEnvironment | AsyncEnvironment

INSTRUCTIONS_CONFLICT_MESSAGE: str = (
    "`instructions` and `dangerously_replace_instructions` are mutually exclusive: "
    "`instructions` appends to the built-in prose, while "
    "`dangerously_replace_instructions` replaces it."
)
RUNTIME_ENVIRONMENT_CONFLICT_MESSAGE: str = "`runtime` cannot be combined with `environment` or `runtime_options`."
DEFER_LOADING_REQUIRES_ID_MESSAGE: str = "`defer_loading=True` requires a stable `id` on the Belgie capability."


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

    def validate(self) -> None:
        if self.instructions is not None and self.dangerously_replace_instructions is not None:
            raise ValueError(INSTRUCTIONS_CONFLICT_MESSAGE)
        if self.runtime is not None and (self.environment is not None or self.runtime_options is not None):
            raise ValueError(RUNTIME_ENVIRONMENT_CONFLICT_MESSAGE)
        if self.defer_loading and self.capability_id is None:
            raise ValueError(DEFER_LOADING_REQUIRES_ID_MESSAGE)

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
        }
