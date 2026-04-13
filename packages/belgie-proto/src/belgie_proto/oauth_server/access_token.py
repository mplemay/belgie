from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.oauth_server.types import OAuthServerAudience


@runtime_checkable
class OAuthServerAccessTokenProtocol(Protocol):
    id: UUID
    token_hash: str
    client_id: str
    scopes: list[str]
    resource: OAuthServerAudience | None
    refresh_token_id: UUID | None
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    expires_at: datetime
