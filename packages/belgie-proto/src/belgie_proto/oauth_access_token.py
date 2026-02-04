from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OAuthAccessTokenProtocol(Protocol):
    id: UUID
    token: str
    client_id: str
    session_id: UUID | None
    user_id: UUID | None
    reference_id: str | None
    refresh_id: UUID | None
    scopes: list[str]
    resource: str | None
    created_at: datetime
    expires_at: datetime
