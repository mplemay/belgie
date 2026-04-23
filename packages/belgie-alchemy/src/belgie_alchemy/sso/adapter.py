from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.sso import SSOAdapterProtocol
from belgie_proto.sso.provider import OIDCConfigValue, SAMLConfigValue, SSOProviderProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.sso.domain import SSODomainProtocol


class SSOAdapter[
    ProviderT: SSOProviderProtocol,
    DomainT: SSODomainProtocol,
](SSOAdapterProtocol[ProviderT, DomainT]):
    def __init__(
        self,
        *,
        sso_provider: type[ProviderT],
        sso_domain: type[DomainT],
    ) -> None:
        self.sso_provider_model = sso_provider
        self.sso_domain_model = sso_domain

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
    ) -> ProviderT:
        provider = self.sso_provider_model(
            organization_id=organization_id,
            created_by_individual_id=created_by_individual_id,
            provider_type=provider_type,
            provider_id=provider_id,
            issuer=issuer,
            oidc_config=oidc_config,
            saml_config=saml_config,
        )
        session.add(provider)
        try:
            await session.commit()
            await session.refresh(provider)
        except Exception:
            await session.rollback()
            raise
        return provider

    async def get_provider_by_id(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> ProviderT | None:
        stmt = select(self.sso_provider_model).where(self.sso_provider_model.id == sso_provider_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_provider_by_provider_id(
        self,
        session: DBConnection,
        *,
        provider_id: str,
    ) -> ProviderT | None:
        stmt = select(self.sso_provider_model).where(self.sso_provider_model.provider_id == provider_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_providers_for_organization(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[ProviderT]:
        stmt = select(self.sso_provider_model).where(self.sso_provider_model.organization_id == organization_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_providers_for_individual(
        self,
        session: DBConnection,
        *,
        individual_id: UUID,
    ) -> list[ProviderT]:
        stmt = select(self.sso_provider_model).where(self.sso_provider_model.created_by_individual_id == individual_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

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
    ) -> ProviderT | None:
        provider = await self.get_provider_by_id(session, sso_provider_id=sso_provider_id)
        if provider is None:
            return None

        if organization_id is not None or (
            created_by_individual_id is not None and getattr(provider, "created_by_individual_id", None) is None
        ):
            provider.organization_id = organization_id
            provider.created_by_individual_id = created_by_individual_id
        if provider_type is not None:
            provider.provider_type = provider_type
        if issuer is not None:
            provider.issuer = issuer
        if oidc_config is not None:
            provider.oidc_config = oidc_config
        if saml_config is not None:
            provider.saml_config = saml_config
        provider.updated_at = datetime.now(UTC)

        try:
            await session.commit()
            await session.refresh(provider)
        except Exception:
            await session.rollback()
            raise
        return provider

    async def delete_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> bool:
        stmt = delete(self.sso_provider_model).where(self.sso_provider_model.id == sso_provider_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_domain(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
        domain: str,
        verification_token: str,
        verification_token_expires_at: datetime | None = None,
    ) -> DomainT:
        sso_domain = self.sso_domain_model(
            sso_provider_id=sso_provider_id,
            domain=domain,
            verification_token=verification_token,
            verification_token_expires_at=verification_token_expires_at,
        )
        session.add(sso_domain)
        try:
            await session.commit()
            await session.refresh(sso_domain)
        except Exception:
            await session.rollback()
            raise
        return sso_domain

    async def get_domain(
        self,
        session: DBConnection,
        *,
        domain_id: UUID,
    ) -> DomainT | None:
        stmt = select(self.sso_domain_model).where(self.sso_domain_model.id == domain_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_domain_by_name(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> DomainT | None:
        stmt = select(self.sso_domain_model).where(self.sso_domain_model.domain == domain)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_verified_domain(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> DomainT | None:
        stmt = select(self.sso_domain_model).where(
            self.sso_domain_model.domain == domain,
            self.sso_domain_model.verified_at.is_not(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_verified_domains_matching(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> list[DomainT]:
        stmt = select(self.sso_domain_model).where(self.sso_domain_model.verified_at.is_not(None))
        result = await session.execute(stmt)
        return [item for item in result.scalars().all() if item.domain == domain or domain.endswith(f".{item.domain}")]

    async def list_domains_matching(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> list[DomainT]:
        stmt = select(self.sso_domain_model)
        result = await session.execute(stmt)
        return [item for item in result.scalars().all() if item.domain == domain or domain.endswith(f".{item.domain}")]

    async def list_domains_for_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> list[DomainT]:
        stmt = select(self.sso_domain_model).where(self.sso_domain_model.sso_provider_id == sso_provider_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_domain(
        self,
        session: DBConnection,
        *,
        domain_id: UUID,
        verification_token: str | None = None,
        verification_token_expires_at: datetime | None = None,
        verified_at: datetime | None = None,
    ) -> DomainT | None:
        sso_domain = await self.get_domain(session, domain_id=domain_id)
        if sso_domain is None:
            return None

        if verification_token is not None:
            sso_domain.verification_token = verification_token
        if verification_token_expires_at is not None:
            sso_domain.verification_token_expires_at = verification_token_expires_at
        sso_domain.verified_at = verified_at
        sso_domain.updated_at = datetime.now(UTC)

        try:
            await session.commit()
            await session.refresh(sso_domain)
        except Exception:
            await session.rollback()
            raise
        return sso_domain

    async def delete_domain(
        self,
        session: DBConnection,
        *,
        domain_id: UUID,
    ) -> bool:
        stmt = delete(self.sso_domain_model).where(self.sso_domain_model.id == domain_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def delete_domains_for_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
    ) -> int:
        stmt = delete(self.sso_domain_model).where(self.sso_domain_model.sso_provider_id == sso_provider_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount  # type: ignore[attr-defined]
