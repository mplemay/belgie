from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class TeamMemberProtocol(Protocol):
    id: UUID
    team_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
