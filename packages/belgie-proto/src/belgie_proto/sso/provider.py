from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


type OIDCConfigValue = str | list[str] | dict[str, str]


@runtime_checkable
class SSOProviderProtocol(Protocol):
    id: UUID
    organization_id: UUID
    provider_id: str
    issuer: str
    oidc_config: dict[str, OIDCConfigValue]
    created_at: datetime
    updated_at: datetime
