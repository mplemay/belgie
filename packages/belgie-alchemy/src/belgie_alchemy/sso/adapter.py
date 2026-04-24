from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.sso import DomainVerificationState, SSOAdapterProtocol
from belgie_proto.sso.provider import OIDCConfigValue, SAMLConfigValue, SSOProviderProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


class SSOAdapter[ProviderT: SSOProviderProtocol](SSOAdapterProtocol[ProviderT]):
    def __init__(
        self,
        *,
        sso_provider: type[ProviderT],
    ) -> None:
        self.sso_provider_model = sso_provider

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
    ) -> ProviderT:
        provider = self.sso_provider_model(
            organization_id=organization_id,
            created_by_individual_id=created_by_individual_id,
            provider_type=provider_type,
            provider_id=provider_id,
            issuer=issuer,
            domain=domain,
            domain_verified=domain_verification.verified if domain_verification is not None else False,
            domain_verification_token=domain_verification.token if domain_verification is not None else None,
            domain_verification_token_expires_at=(
                domain_verification.token_expires_at if domain_verification is not None else None
            ),
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

    async def get_provider_by_domain(
        self,
        session: DBConnection,
        *,
        domain: str,
    ) -> ProviderT | None:
        stmt = select(self.sso_provider_model)
        result = await session.execute(stmt)
        return next((item for item in result.scalars().all() if domain in _provider_domains(item.domain)), None)

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
        stmt = select(self.sso_provider_model).where(
            self.sso_provider_model.created_by_individual_id == individual_id,
            self.sso_provider_model.organization_id.is_(None),
        )
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
        domain: str | None = None,
        domain_verification: DomainVerificationState | None = None,
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
        if domain is not None:
            provider.domain = domain
        if domain_verification is not None:
            provider.domain_verified = domain_verification.verified
            provider.domain_verification_token = domain_verification.token
            provider.domain_verification_token_expires_at = domain_verification.token_expires_at
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

    async def list_providers_matching_domain(
        self,
        session: DBConnection,
        *,
        domain: str,
        verified_only: bool,
    ) -> list[ProviderT]:
        stmt = select(self.sso_provider_model)
        result = await session.execute(stmt)
        return [
            item
            for item in result.scalars().all()
            if (not verified_only or item.domain_verified) and _provider_matches_domain(item.domain, domain)
        ]


def _provider_domains(value: str) -> tuple[str, ...]:
    return tuple(domain.strip() for domain in value.split(",") if domain.strip())


def _provider_matches_domain(domain_value: str, domain: str) -> bool:
    return any(candidate == domain or domain.endswith(f".{candidate}") for candidate in _provider_domains(domain_value))
