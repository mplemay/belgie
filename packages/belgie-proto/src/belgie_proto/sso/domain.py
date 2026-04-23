from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@runtime_checkable
class SSODomainProtocol(Protocol):
    id: UUID
    sso_provider_id: UUID
    domain: str
    verification_token: str
    verification_token_expires_at: datetime | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
