from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Literal
    from uuid import UUID


@runtime_checkable
class OAuthStateProtocol(Protocol):
    id: UUID
    state: str
    provider: str | None
    individual_id: UUID | None
    code_verifier: str | None
    nonce: str | None
    intent: Literal["signin", "link"]
    redirect_url: str | None
    error_redirect_url: str | None
    new_user_redirect_url: str | None
    payload: Any | None
    request_sign_up: bool
    created_at: datetime
    expires_at: datetime
