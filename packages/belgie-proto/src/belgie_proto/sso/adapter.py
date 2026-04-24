from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.sso.provider import OIDCConfigValue, SAMLConfigValue, SSOProviderProtocol

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.sso.types import DomainVerificationState


@runtime_checkable
class SSOAdapterProtocol[ProviderT: SSOProviderProtocol](Protocol):
    async def create_provider(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        organization_id: UUID | None,
        created_by_individual_id: UUID | None,
        provider_type: str,
        provider_id: str,
        issuer: str,
        domain: str,
        domain_verification: DomainVerificationState | None,
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

    async def get_provider_by_domain(
        self,
        session: DBConnection,
        *,
        domain: str,
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
        domain: str | None = None,
        domain_verification: DomainVerificationState | None = None,
        oidc_config: dict[str, OIDCConfigValue] | None = None,
        saml_config: dict[str, SAMLConfigValue] | None = None,
    ) -> ProviderT | None: ...

    async def delete_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> bool: ...

    async def list_providers_matching_domain(
        self,
        session: DBConnection,
        *,
        domain: str,
        verified_only: bool,
    ) -> list[ProviderT]: ...
