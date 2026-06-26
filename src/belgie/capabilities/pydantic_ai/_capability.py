from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic_ai.capabilities import AbstractCapability, CapabilityOrdering
from pydantic_ai.tools import AgentDepsT

from belgie.capabilities.pydantic_ai._toolset import BelgieToolset, _BelgieOptions

if TYPE_CHECKING:
    from pydantic_ai import AbstractToolset


@dataclass(kw_only=True)
class Belgie(_BelgieOptions, AbstractCapability[AgentDepsT]):
    def __post_init__(self) -> None:
        self.validate()

    def get_ordering(self) -> CapabilityOrdering:
        return CapabilityOrdering(position="outermost")

    def get_wrapper_toolset(self, toolset: AbstractToolset[AgentDepsT]) -> AbstractToolset[AgentDepsT] | None:
        return cast(
            "AbstractToolset[AgentDepsT]",
            BelgieToolset(wrapped=toolset, **self.options_kwargs()),
        )
