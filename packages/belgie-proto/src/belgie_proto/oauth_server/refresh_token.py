from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OAuthServerRefreshTokenProtocol(Protocol):
    """Opaque refresh token row. ``auth_time`` is not a stored field here — OIDC
    ``auth_time`` for ``id_token`` is taken from the active session in the
    server layer when tokens are produced.
    """

    id: UUID
    token_hash: str
    client_id: str
    scopes: list[str]
    resource: str | None
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
