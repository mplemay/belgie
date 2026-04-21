from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.sso import SSOAdapterProtocol
from belgie_proto.sso.provider import OIDCConfigValue, SSOProviderProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.sso.domain import SSODomainProtocol


def _domain_matches(search_domain: str, registered_domain: str) -> bool:
    search = search_domain.lower()
    registered = registered_domain.lower()
    return search == registered or search.endswith(f".{registered}")


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

    async def create_provider(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        provider_id: str,
        issuer: str,
        oidc_config: dict[str, OIDCConfigValue],
    ) -> ProviderT:
        provider = self.sso_provider_model(
            organization_id=organization_id,
            provider_id=provider_id,
            issuer=issuer,
            oidc_config=oidc_config,
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

    async def update_provider(
        self,
        session: DBConnection,
        *,
        sso_provider_id: UUID,
        issuer: str | None = None,
        oidc_config: dict[str, OIDCConfigValue] | None = None,
    ) -> ProviderT | None:
        provider = await self.get_provider_by_id(session, sso_provider_id=sso_provider_id)
        if provider is None:
            return None

        if issuer is not None:
            provider.issuer = issuer
        if oidc_config is not None:
            provider.oidc_config = oidc_config
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
    ) -> DomainT:
        sso_domain = self.sso_domain_model(
            sso_provider_id=sso_provider_id,
            domain=domain,
            verification_token=verification_token,
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

    async def get_best_verified_domain(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> DomainT | None:
        stmt = select(self.sso_domain_model).where(self.sso_domain_model.verified_at.is_not(None))
        result = await session.execute(stmt)
        matches = [item for item in result.scalars().all() if _domain_matches(domain, item.domain)]
        if not matches:
            return None
        matches.sort(key=lambda item: len(item.domain), reverse=True)
        return matches[0]

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
        verified_at: datetime | None = None,
    ) -> DomainT | None:
        sso_domain = await self.get_domain(session, domain_id=domain_id)
        if sso_domain is None:
            return None

        if verification_token is not None:
            sso_domain.verification_token = verification_token
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
