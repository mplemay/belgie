from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic_ai.capabilities import AbstractCapability, CapabilityOrdering
from pydantic_ai.tools import AgentDepsT

from belgie.capabilities.core._run_code import (
    DEFAULT_BELGIE_CAPABILITY_DESCRIPTION,
    DEFAULT_BELGIE_CAPABILITY_ID,
)
from belgie.capabilities.pydantic_ai._toolset import (
    BelgieToolset,
    _BelgieOptions,
)

if TYPE_CHECKING:
    from pydantic_ai import AbstractToolset


@dataclass(kw_only=True)
class Belgie(_BelgieOptions, AbstractCapability[AgentDepsT]):
    def __post_init__(self) -> None:
        if self.defer_loading and self.id is None:
            self.id = DEFAULT_BELGIE_CAPABILITY_ID
        if self.defer_loading and self.description is None:
            self.description = DEFAULT_BELGIE_CAPABILITY_DESCRIPTION
        if self.capability_id is None:
            self.capability_id = self.id
        self.validate()

    def get_ordering(self) -> CapabilityOrdering:
        return CapabilityOrdering(position="outermost")

    def get_wrapper_toolset(self, toolset: AbstractToolset[AgentDepsT]) -> AbstractToolset[AgentDepsT] | None:
        return cast(
            "AbstractToolset[AgentDepsT]",
            BelgieToolset(wrapped=toolset, **self.options_kwargs()),
        )
