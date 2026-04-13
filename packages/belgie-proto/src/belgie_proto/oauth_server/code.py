from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OAuthAuthorizationCodeProtocol(Protocol):
    id: UUID
    code_hash: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str | None
    scopes: list[str]
    resource: str | None
    nonce: str | None
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    expires_at: datetime
