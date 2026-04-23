from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.sso.domain import SSODomainProtocol
from belgie_proto.sso.provider import OIDCConfigValue, SAMLConfigValue, SSOProviderProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


@runtime_checkable
class SSOAdapterProtocol[
    ProviderT: SSOProviderProtocol,
    DomainT: SSODomainProtocol,
](Protocol):
    async def create_provider(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        organization_id: UUID | None,
        created_by_individual_id: UUID | None,
        provider_type: str,
        provider_id: str,
        issuer: str,
        oidc_config: dict[str, OIDCConfigValue] | None,
        saml_config: dict[str, SAMLConfigValue] | None,
    ) -> ProviderT: ...

    async def get_provider_by_id(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> ProviderT | None: ...

    async def get_provider_by_provider_id(
        self,
        session: DBConnection,
        *,
        provider_id: str,
    ) -> ProviderT | None: ...

    async def list_providers_for_organization(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[ProviderT]: ...

    async def list_providers_for_individual(
        self,
        session: DBConnection,
        *,
        individual_id: UUID,
    ) -> list[ProviderT]: ...

    async def update_provider(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
        organization_id: UUID | None = None,
        created_by_individual_id: UUID | None = None,
        provider_type: str | None = None,
        issuer: str | None = None,
        oidc_config: dict[str, OIDCConfigValue] | None = None,
        saml_config: dict[str, SAMLConfigValue] | None = None,
    ) -> ProviderT | None: ...

    async def delete_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> bool: ...

    async def create_domain(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
        domain: str,
        verification_token: str,
        verification_token_expires_at: datetime | None = None,
    ) -> DomainT: ...

    async def get_domain(
        self,
        session: DBConnection,
        *,
        domain_id: UUID,
    ) -> DomainT | None: ...

    async def get_domain_by_name(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> DomainT | None: ...

    async def get_verified_domain(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> DomainT | None: ...

    async def list_verified_domains_matching(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> list[DomainT]: ...

    async def list_domains_matching(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> list[DomainT]: ...

    async def list_domains_for_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> list[DomainT]: ...

    async def update_domain(
        self,
        session: DBConnection,
        *,
        domain_id: UUID,
        verification_token: str | None = None,
        verification_token_expires_at: datetime | None = None,
        verified_at: datetime | None = None,
    ) -> DomainT | None: ...

    async def delete_domain(
        self,
        session: DBConnection,
        *,
        domain_id: UUID,
    ) -> bool: ...

    async def delete_domains_for_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> int: ...
