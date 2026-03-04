from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class InvitationProtocol(Protocol):
    id: UUID
    organization_id: UUID
    email: str
    role: str
    status: str
    inviter_id: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
