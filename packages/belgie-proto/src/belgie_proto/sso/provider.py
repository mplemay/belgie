from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


type SSOProviderType = str
type ClaimMappingValue = str | dict[str, str]
type OIDCConfigValue = str | bool | list[str] | dict[str, ClaimMappingValue]
type SAMLConfigValue = str | bool | list[str] | dict[str, ClaimMappingValue]


@runtime_checkable
class SSOProviderProtocol(Protocol):
    id: UUID
    organization_id: UUID | None
    created_by_individual_id: UUID | None
    provider_type: SSOProviderType
    provider_id: str
    issuer: str
    domain: str
    domain_verified: bool
    domain_verification_token: str | None
    domain_verification_token_expires_at: datetime | None
    oidc_config: dict[str, OIDCConfigValue] | None
    saml_config: dict[str, SAMLConfigValue] | None
    created_at: datetime
    updated_at: datetime
