from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Final, NotRequired, cast

from langchain.agents.middleware import AgentState
from langchain.agents.middleware.types import PrivateStateAttr

from belgie.agent._runtime import BelgieRuntimeSession  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

BELGIE_RUNTIME_SESSION_STATE_KEY: Final[str] = "belgie_runtime_session"


class BelgieAgentState(AgentState[Any]):
    belgie_runtime_session: NotRequired[Annotated[BelgieRuntimeSession | None, PrivateStateAttr]]


def session_from_state(state: Mapping[str, Any]) -> BelgieRuntimeSession | None:
    return cast("BelgieRuntimeSession | None", state.get(BELGIE_RUNTIME_SESSION_STATE_KEY))
