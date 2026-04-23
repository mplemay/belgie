from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.json import JSONValue


@dataclass(slots=True, kw_only=True, frozen=True)
class SSODomainChallenge:
    domain: str
    record_name: str
    record_value: str
    verification_token: str
    expires_at: datetime | None
    verified_at: datetime | None


@dataclass(slots=True, kw_only=True, frozen=True)
class SSOProviderSummary:
    id: UUID
    provider_id: str
    provider_type: str
    issuer: str
    organization_id: UUID | None
    created_by_individual_id: UUID | None
    client_id: str | None
    domain_verified: bool
    domains: tuple[str, ...]
    verified_domains: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, kw_only=True, frozen=True)
class SSOProviderDetail:
    id: UUID
    provider_id: str
    provider_type: str
    issuer: str
    organization_id: UUID | None
    created_by_individual_id: UUID | None
    domain_verified: bool
    domains: tuple[str, ...]
    verified_domains: tuple[str, ...]
    config: dict[str, JSONValue]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, kw_only=True, frozen=True)
class SSOProvisioningContext:
    provider_id: str
    provider_type: str
    profile: dict[str, JSONValue]
    token_payload: dict[str, JSONValue] | None
    created: bool
