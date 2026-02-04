from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OAuthRefreshTokenProtocol(Protocol):
    id: UUID
    token: str
    client_id: str
    session_id: UUID | None
    user_id: UUID
    reference_id: str | None
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    revoked: datetime | None
