from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OAuthAuthorizationCodeProtocol(Protocol):
    id: UUID
    code: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    code_challenge_method: str | None
    scopes: list[str]
    user_id: UUID
    session_id: UUID | None
    reference_id: str | None
    created_at: datetime
    expires_at: datetime
