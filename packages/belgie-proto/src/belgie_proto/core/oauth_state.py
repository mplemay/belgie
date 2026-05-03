from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

type OAuthFlowIntent = Literal["signin", "link"]

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.json import JSONValue


@runtime_checkable
class OAuthStateProtocol(Protocol):
    id: UUID
    state: str
    provider: str | None
    individual_id: UUID | None
    code_verifier: str | None
    nonce: str | None
    intent: OAuthFlowIntent
    redirect_url: str | None
    error_redirect_url: str | None
    new_user_redirect_url: str | None
    payload: JSONValue
    request_sign_up: bool
    created_at: datetime
    expires_at: datetime


__all__ = [
    "OAuthFlowIntent",
    "OAuthStateProtocol",
]
