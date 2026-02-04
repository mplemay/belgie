from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class OAuthConsentProtocol(Protocol):
    id: UUID
    client_id: str
    user_id: UUID
    reference_id: str | None
    scopes: list[str]
    created_at: datetime
    updated_at: datetime
