from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.oauth_server.types import AuthorizationIntent


@runtime_checkable
class OAuthAuthorizationStateProtocol(Protocol):
    id: UUID
    state: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str | None
    resource: str | None
    scopes: list[str] | None
    nonce: str | None
    prompt: str | None
    intent: AuthorizationIntent
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
