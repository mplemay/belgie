from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class MemberProtocol(Protocol):
    id: UUID
    organization_id: UUID
    individual_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime
