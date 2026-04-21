from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003

from belgie_organization.roles import has_any_role
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig, SSODomainProtocol, SSOProviderProtocol
from fastapi import HTTPException, status

from belgie_sso.discovery import OIDCDiscoveryResult, compute_discovery_url, discover_oidc_configuration
from belgie_sso.dns import lookup_txt_records
from belgie_sso.utils import (
    deserialize_oidc_config,
    mask_client_id,
    normalize_domain,
    normalize_issuer,
    normalize_provider_id,
    serialize_oidc_config,
)

if TYPE_CHECKING:
    from belgie_core.core.client import BelgieClient
    from belgie_proto.core.individual import IndividualProtocol
    from belgie_proto.organization import OrganizationAdapterProtocol

    from belgie_sso.settings import EnterpriseSSO


@dataclass(frozen=True, slots=True, kw_only=True)
class SanitizedOIDCProviderConfig:
    client_id_last_four: str
    authorization_endpoint: str | None
    token_endpoint: str | None
    userinfo_endpoint: str | None
    jwks_uri: str | None
    discovery_endpoint: str | None
    scopes: tuple[str, ...]
    token_endpoint_auth_method: str
    pkce: bool
    override_user_info: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class SanitizedSSOProvider[
    DomainT: SSODomainProtocol,
]:
    provider_id: str
    issuer: str
    organization_id: UUID
    oidc_config: SanitizedOIDCProviderConfig
    domains: list[DomainT]


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
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT]
    current_individual: IndividualProtocol[str]

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
        discovery_endpoint: str | None = None,
        authorization_endpoint: str | None = None,
        token_endpoint: str | None = None,
        userinfo_endpoint: str | None = None,
        jwks_uri: str | None = None,
        pkce: bool = True,
        override_user_info: bool = False,
        skip_discovery: bool = False,
    ) -> ProviderT:
        await self._require_org_admin(organization_id=organization_id)
        await self._enforce_provider_limit(organization_id=organization_id)

        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        if await self.settings.adapter.get_provider_by_provider_id(self.client.db, provider_id=normalized_provider_id):
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

        resolved_config = await self._resolve_oidc_configuration(
            issuer=issuer,
            client_id=client_id.strip(),
            client_secret=client_secret.strip(),
            scopes=scopes or self.settings.default_scopes,
            token_endpoint_auth_method=token_endpoint_auth_method,
            claim_mapping=claim_mapping or OIDCClaimMapping(),
            discovery_endpoint=discovery_endpoint,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            userinfo_endpoint=userinfo_endpoint,
            jwks_uri=jwks_uri,
            pkce=pkce,
            override_user_info=override_user_info,
            skip_discovery=skip_discovery,
        )

        provider = await self.settings.adapter.create_provider(
            self.client.db,
            organization_id=organization_id,
            provider_id=normalized_provider_id,
            issuer=resolved_config.issuer,
            oidc_config=serialize_oidc_config(resolved_config.config),
        )

        try:
            for domain in normalized_domains:
                await self.settings.adapter.create_domain(
                    self.client.db,
                    sso_provider_id=provider.id,
                    domain=domain,
                    verification_token=self._generate_verification_token(),
                )
        except Exception:
            await self.settings.adapter.delete_provider(self.client.db, sso_provider_id=provider.id)
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
        discovery_endpoint: str | None = None,
        authorization_endpoint: str | None = None,
        token_endpoint: str | None = None,
        userinfo_endpoint: str | None = None,
        jwks_uri: str | None = None,
        pkce: bool | None = None,
        override_user_info: bool | None = None,
        skip_discovery: bool = False,
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
        next_discovery_endpoint = discovery_endpoint or existing_config.discovery_endpoint
        next_authorization_endpoint = authorization_endpoint or existing_config.authorization_endpoint
        next_token_endpoint = token_endpoint or existing_config.token_endpoint
        next_userinfo_endpoint = userinfo_endpoint or existing_config.userinfo_endpoint
        next_jwks_uri = jwks_uri or existing_config.jwks_uri
        next_pkce = existing_config.pkce if pkce is None else pkce
        next_override_user_info = (
            existing_config.override_user_info if override_user_info is None else override_user_info
        )

        resolved_config = await self._resolve_oidc_configuration(
            issuer=next_issuer,
            client_id=next_client_id,
            client_secret=next_client_secret,
            scopes=next_scopes,
            token_endpoint_auth_method=next_auth_method,
            claim_mapping=next_claim_mapping,
            discovery_endpoint=next_discovery_endpoint,
            authorization_endpoint=next_authorization_endpoint,
            token_endpoint=next_token_endpoint,
            userinfo_endpoint=next_userinfo_endpoint,
            jwks_uri=next_jwks_uri,
            pkce=next_pkce,
            override_user_info=next_override_user_info,
            skip_discovery=skip_discovery,
        )

        updated_provider = await self.settings.adapter.update_provider(
            self.client.db,
            sso_provider_id=provider.id,
            issuer=resolved_config.issuer,
            oidc_config=serialize_oidc_config(resolved_config.config),
        )
        if updated_provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )

        if domains is not None:
            normalized_domains = self._normalize_domains(domains)
            await self._ensure_domains_are_available(normalized_domains, sso_provider_id=provider.id)
            existing = await self.settings.adapter.list_domains_for_provider(
                self.client.db,
                sso_provider_id=provider.id,
            )
            existing_by_name = {d.domain: d for d in existing}
            new_set = set(normalized_domains)
            for row in existing:
                if row.domain not in new_set:
                    await self.settings.adapter.delete_domain(self.client.db, domain_id=row.id)
            for name in normalized_domains:
                if name not in existing_by_name:
                    await self.settings.adapter.create_domain(
                        self.client.db,
                        sso_provider_id=provider.id,
                        domain=name,
                        verification_token=self._generate_verification_token(),
                    )

        return updated_provider

    async def delete_provider(self, *, provider_id: str) -> bool:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)
        return await self.settings.adapter.delete_provider(self.client.db, sso_provider_id=provider.id)

    async def get_provider(self, *, provider_id: str) -> ProviderT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)
        return provider

    async def list_providers(self, *, organization_id: UUID) -> list[ProviderT]:
        await self._require_org_admin(organization_id=organization_id)
        return await self.settings.adapter.list_providers_for_organization(
            self.client.db,
            organization_id=organization_id,
        )

    async def get_provider_details(self, *, provider_id: str) -> SanitizedSSOProvider[DomainT]:
        provider = await self.get_provider(provider_id=provider_id)
        domains = await self.settings.adapter.list_domains_for_provider(
            self.client.db,
            sso_provider_id=provider.id,
        )
        return self._sanitize_provider(provider=provider, domains=domains)

    async def list_provider_details(self, *, organization_id: UUID) -> list[SanitizedSSOProvider[DomainT]]:
        providers = await self.list_providers(organization_id=organization_id)
        sanitized: list[SanitizedSSOProvider[DomainT]] = []
        for provider in providers:
            domains = await self.settings.adapter.list_domains_for_provider(
                self.client.db,
                sso_provider_id=provider.id,
            )
            sanitized.append(self._sanitize_provider(provider=provider, domains=domains))
        return sanitized

    async def create_domain_challenge(self, *, provider_id: str, domain: str) -> DomainT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_org_admin(organization_id=provider.organization_id)

        normalized_domain = normalize_domain(domain)
        existing = await self.settings.adapter.get_domain_by_name(self.client.db, domain=normalized_domain)
        token = self._generate_verification_token()
        if existing is None:
            return await self.settings.adapter.create_domain(
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

        updated = await self.settings.adapter.update_domain(
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
        sso_domain = await self.settings.adapter.get_domain_by_name(self.client.db, domain=normalized_domain)
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

        verified_domain = await self.settings.adapter.update_domain(
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
        provider = await self.settings.adapter.get_provider_by_provider_id(
            self.client.db,
            provider_id=normalized_provider_id,
        )
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
        return provider

    async def _resolve_oidc_configuration(  # noqa: PLR0913
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        scopes: list[str],
        token_endpoint_auth_method: str,
        claim_mapping: OIDCClaimMapping,
        discovery_endpoint: str | None,
        authorization_endpoint: str | None,
        token_endpoint: str | None,
        userinfo_endpoint: str | None,
        jwks_uri: str | None,
        pkce: bool,
        override_user_info: bool,
        skip_discovery: bool,
    ) -> OIDCDiscoveryResult:
        normalized_issuer = normalize_issuer(issuer)
        resolved_discovery_endpoint = compute_discovery_url(
            issuer=normalized_issuer,
            discovery_endpoint=discovery_endpoint,
        )
        if skip_discovery:
            if not authorization_endpoint:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="authorization_endpoint is required when skip_discovery is enabled",
                )
            if not token_endpoint:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="token_endpoint is required when skip_discovery is enabled",
                )
            if not userinfo_endpoint and not jwks_uri:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="userinfo_endpoint or jwks_uri is required when skip_discovery is enabled",
                )
            return OIDCDiscoveryResult(
                issuer=normalized_issuer,
                config=OIDCProviderConfig(
                    client_id=client_id,
                    client_secret=client_secret,
                    authorization_endpoint=authorization_endpoint,
                    token_endpoint=token_endpoint,
                    userinfo_endpoint=userinfo_endpoint,
                    jwks_uri=jwks_uri,
                    discovery_endpoint=resolved_discovery_endpoint,
                    scopes=tuple(scopes),
                    token_endpoint_auth_method=token_endpoint_auth_method,
                    claim_mapping=claim_mapping,
                    pkce=pkce,
                    override_user_info=override_user_info,
                ),
            )

        return await discover_oidc_configuration(
            issuer=normalized_issuer,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
            token_endpoint_auth_method=token_endpoint_auth_method,
            claim_mapping=claim_mapping,
            timeout_seconds=self.settings.discovery_timeout_seconds,
            discovery_endpoint=resolved_discovery_endpoint,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            userinfo_endpoint=userinfo_endpoint,
            jwks_uri=jwks_uri,
            pkce=pkce,
            override_user_info=override_user_info,
        )

    def _sanitize_provider(
        self,
        *,
        provider: ProviderT,
        domains: list[DomainT],
    ) -> SanitizedSSOProvider[DomainT]:
        config = deserialize_oidc_config(provider.oidc_config)
        return SanitizedSSOProvider(
            provider_id=provider.provider_id,
            issuer=provider.issuer,
            organization_id=provider.organization_id,
            oidc_config=SanitizedOIDCProviderConfig(
                client_id_last_four=mask_client_id(config.client_id),
                authorization_endpoint=config.authorization_endpoint,
                token_endpoint=config.token_endpoint,
                userinfo_endpoint=config.userinfo_endpoint,
                jwks_uri=config.jwks_uri,
                discovery_endpoint=config.discovery_endpoint,
                scopes=config.scopes,
                token_endpoint_auth_method=config.token_endpoint_auth_method,
                pkce=config.pkce,
                override_user_info=config.override_user_info,
            ),
            domains=domains,
        )

    async def _enforce_provider_limit(self, *, organization_id: UUID) -> None:
        if self.settings.providers_limit is None:
            return
        providers = await self.settings.adapter.list_providers_for_organization(
            self.client.db,
            organization_id=organization_id,
        )
        if len(providers) >= self.settings.providers_limit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization has reached the configured SSO provider limit",
            )

    async def _require_org_admin(self, *, organization_id: UUID) -> None:
        member = await self.organization_adapter.get_member(
            self.client.db,
            organization_id=organization_id,
            individual_id=self.current_individual.id,
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
            if existing := await self.settings.adapter.get_domain_by_name(self.client.db, domain=domain):
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
