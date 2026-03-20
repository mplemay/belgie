from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_organization.roles import has_any_role
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.sso import OIDCClaimMapping, SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol
from fastapi import HTTPException, status

from belgie_sso.discovery import discover_oidc_configuration
from belgie_sso.dns import lookup_txt_records
from belgie_sso.utils import (
    deserialize_oidc_config,
    normalize_domain,
    normalize_issuer,
    normalize_provider_id,
    serialize_oidc_config,
)

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_core.core.client import BelgieClient
    from belgie_proto.core.user import UserProtocol
    from belgie_proto.organization import OrganizationAdapterProtocol

    from belgie_sso.settings import EnterpriseSSO


@dataclass(frozen=True, slots=True, kw_only=True)
class SSOClient[
    ProviderT: SSOProviderProtocol,
    DomainT: SSODomainProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
]:
    client: BelgieClient
    settings: EnterpriseSSO[ProviderT, DomainT]
    adapter: SSOAdapterProtocol[ProviderT, DomainT]
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT]
    current_user: UserProtocol[str]

    async def register_oidc_provider(  # noqa: PLR0913
        self,
        *,
        organization_id: UUID,
        provider_id: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        domains: list[str],
        scopes: list[str] | None = None,
        token_endpoint_auth_method: str = "client_secret_basic",  # noqa: S107
        claim_mapping: OIDCClaimMapping | None = None,
    ) -> ProviderT:
        await self._require_org_admin(organization_id=organization_id)

        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        if await self.adapter.get_provider_by_provider_id(self.client.db, provider_id=normalized_provider_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id already exists",
            )

        if await self.organization_adapter.get_organization_by_id(self.client.db, organization_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="organization not found",
            )

        normalized_domains = self._normalize_domains(domains)
        await self._ensure_domains_are_available(normalized_domains)

        discovery = await discover_oidc_configuration(
            issuer=issuer,
            client_id=client_id.strip(),
            client_secret=client_secret.strip(),
            scopes=scopes or self.settings.default_scopes,
            token_endpoint_auth_method=token_endpoint_auth_method,
            claim_mapping=claim_mapping or OIDCClaimMapping(),
            timeout_seconds=self.settings.discovery_timeout_seconds,
        )

        provider = await self.adapter.create_provider(
            self.client.db,
            organization_id=organization_id,
            provider_id=normalized_provider_id,
            issuer=discovery.issuer,
            oidc_config=serialize_oidc_config(discovery.config),
        )

        try:
            for domain in normalized_domains:
                await self.adapter.create_domain(
                    self.client.db,
                    sso_provider_id=provider.id,
                    domain=domain,
                    verification_token=self._generate_verification_token(),
                )
        except Exception:
            await self.adapter.delete_provider(self.client.db, sso_provider_id=provider.id)
            raise

        return provider

    async def update_oidc_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        domains: list[str] | None = None,
        scopes: list[str] | None = None,
        token_endpoint_auth_method: str | None = None,
        claim_mapping: OIDCClaimMapping | None = None,
    ) -> ProviderT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)

        existing_config = deserialize_oidc_config(provider.oidc_config)
        next_issuer = normalize_issuer(issuer or provider.issuer)
        next_client_id = (client_id or existing_config.client_id).strip()
        next_client_secret = (client_secret or existing_config.client_secret).strip()
        next_scopes = scopes or list(existing_config.scopes)
        next_auth_method = token_endpoint_auth_method or existing_config.token_endpoint_auth_method
        next_claim_mapping = claim_mapping or existing_config.claim_mapping

        discovery = await discover_oidc_configuration(
            issuer=next_issuer,
            client_id=next_client_id,
            client_secret=next_client_secret,
            scopes=next_scopes,
            token_endpoint_auth_method=next_auth_method,
            claim_mapping=next_claim_mapping,
            timeout_seconds=self.settings.discovery_timeout_seconds,
        )

        updated_provider = await self.adapter.update_provider(
            self.client.db,
            sso_provider_id=provider.id,
            issuer=discovery.issuer,
            oidc_config=serialize_oidc_config(discovery.config),
        )
        if updated_provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )

        if domains is not None:
            normalized_domains = self._normalize_domains(domains)
            await self._ensure_domains_are_available(normalized_domains, sso_provider_id=provider.id)
            existing = await self.adapter.list_domains_for_provider(
                self.client.db,
                sso_provider_id=provider.id,
            )
            existing_by_name = {d.domain: d for d in existing}
            new_set = set(normalized_domains)
            for row in existing:
                if row.domain not in new_set:
                    await self.adapter.delete_domain(self.client.db, domain_id=row.id)
            for name in normalized_domains:
                if name not in existing_by_name:
                    await self.adapter.create_domain(
                        self.client.db,
                        sso_provider_id=provider.id,
                        domain=name,
                        verification_token=self._generate_verification_token(),
                    )

        return updated_provider

    async def delete_provider(self, *, provider_id: str) -> bool:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)
        return await self.adapter.delete_provider(self.client.db, sso_provider_id=provider.id)

    async def get_provider(self, *, provider_id: str) -> ProviderT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)
        return provider

    async def list_providers(self, *, organization_id: UUID) -> list[ProviderT]:
        await self._require_org_admin(organization_id=organization_id)
        return await self.adapter.list_providers_for_organization(
            self.client.db,
            organization_id=organization_id,
        )

    async def create_domain_challenge(self, *, provider_id: str, domain: str) -> DomainT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)

        normalized_domain = normalize_domain(domain)
        existing = await self.adapter.get_domain_by_name(self.client.db, domain=normalized_domain)
        token = self._generate_verification_token()
        if existing is None:
            return await self.adapter.create_domain(
                self.client.db,
                sso_provider_id=provider.id,
                domain=normalized_domain,
                verification_token=token,
            )

        if existing.sso_provider_id != provider.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="domain is already registered to another provider",
            )

        updated = await self.adapter.update_domain(
            self.client.db,
            domain_id=existing.id,
            verification_token=token,
            verified_at=None,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="domain not found",
            )
        return updated

    async def verify_domain(self, *, provider_id: str, domain: str) -> DomainT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)

        normalized_domain = normalize_domain(domain)
        sso_domain = await self.adapter.get_domain_by_name(self.client.db, domain=normalized_domain)
        if sso_domain is None or sso_domain.sso_provider_id != provider.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="domain not found for provider",
            )

        record_name = f"{self.settings.domain_txt_prefix}.{normalized_domain}"
        records = await lookup_txt_records(record_name)
        if sso_domain.verification_token not in records:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="verification token not found in DNS TXT records",
            )

        verified_domain = await self.adapter.update_domain(
            self.client.db,
            domain_id=sso_domain.id,
            verified_at=datetime.now(UTC),
        )
        if verified_domain is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="domain not found",
            )
        return verified_domain

    def _normalize_provider_id_or_400(self, provider_id: str) -> str:
        try:
            return normalize_provider_id(provider_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    async def _get_provider_or_404(self, provider_id: str) -> ProviderT:
        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        provider = await self.adapter.get_provider_by_provider_id(
            self.client.db,
            provider_id=normalized_provider_id,
        )
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
        return provider

    async def _require_org_admin(self, *, organization_id: UUID) -> None:
        member = await self.organization_adapter.get_member(
            self.client.db,
            organization_id=organization_id,
            user_id=self.current_user.id,
        )
        if member is None or not has_any_role(member.role, ["owner", "admin"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization admin access is required",
            )

    async def _ensure_domains_are_available(
        self,
        domains: list[str],
        *,
        sso_provider_id: UUID | None = None,
    ) -> None:
        for domain in domains:
            if existing := await self.adapter.get_domain_by_name(self.client.db, domain=domain):
                if sso_provider_id is not None and existing.sso_provider_id == sso_provider_id:
                    continue
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"domain '{domain}' is already registered",
                )

    def _normalize_domains(self, domains: list[str]) -> list[str]:
        normalized: list[str] = []
        for domain in domains:
            value = normalize_domain(domain)
            if value in normalized:
                continue
            normalized.append(value)
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="at least one domain is required",
            )
        return normalized

    def _generate_verification_token(self) -> str:
        return secrets.token_urlsafe(24)
