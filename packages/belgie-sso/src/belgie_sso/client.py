from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_organization.roles import has_any_role
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.sso import (
    OIDCClaimMapping,
    OIDCProviderConfig,
    SAMLProviderConfig,
    SSODomainProtocol,
    SSOProviderProtocol,
)
from fastapi import HTTPException, status

from belgie_sso.discovery import discover_oidc_configuration
from belgie_sso.dns import lookup_txt_records
from belgie_sso.models import SSODomainChallenge, SSOProviderSummary
from belgie_sso.utils import (
    build_domain_verification_record_name,
    build_domain_verification_record_value,
    deserialize_oidc_config,
    mask_client_id,
    normalize_domain,
    normalize_issuer,
    normalize_provider_id,
    serialize_oidc_config,
    serialize_saml_config,
)

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_core.core.client import BelgieClient
    from belgie_proto.core.individual import IndividualProtocol
    from belgie_proto.organization import OrganizationAdapterProtocol

    from belgie_sso.settings import EnterpriseSSO

_DNS_LABEL_MAX_LENGTH = 63


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
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT] | None = None
    current_individual: IndividualProtocol[str] | None = None

    async def register_oidc_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        domains: list[str] | None = None,
        organization_id: UUID | None = None,
        scopes: list[str] | None = None,
        token_endpoint_auth_method: str = "client_secret_basic",  # noqa: S107
        claim_mapping: OIDCClaimMapping | None = None,
        authorization_endpoint: str | None = None,
        token_endpoint: str | None = None,
        userinfo_endpoint: str | None = None,
        jwks_uri: str | None = None,
        discovery_endpoint: str | None = None,
        use_pkce: bool = True,
        override_user_info_on_sign_in: bool = False,
        skip_discovery: bool = False,
    ) -> ProviderT:
        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        if await self.settings.adapter.get_provider_by_provider_id(self.client.db, provider_id=normalized_provider_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id already exists",
            )

        await self._require_registration_access(organization_id=organization_id)
        await self._ensure_provider_capacity(organization_id=organization_id)
        normalized_domains = self._normalize_domains(domains)
        await self._ensure_domains_are_available(normalized_domains)

        config = await self._resolve_oidc_config(
            issuer=issuer,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
            token_endpoint_auth_method=token_endpoint_auth_method,
            claim_mapping=claim_mapping,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            userinfo_endpoint=userinfo_endpoint,
            jwks_uri=jwks_uri,
            discovery_endpoint=discovery_endpoint,
            use_pkce=use_pkce,
            override_user_info_on_sign_in=override_user_info_on_sign_in,
            skip_discovery=skip_discovery,
        )

        provider = await self.settings.adapter.create_provider(
            self.client.db,
            organization_id=organization_id,
            created_by_individual_id=None if organization_id else self._current_individual_or_403().id,
            provider_type="oidc",
            provider_id=normalized_provider_id,
            issuer=config.issuer,
            oidc_config=serialize_oidc_config(config),
            saml_config=None,
        )
        try:
            await self._sync_provider_domains(provider=provider, domains=normalized_domains)
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
        authorization_endpoint: str | None = None,
        token_endpoint: str | None = None,
        userinfo_endpoint: str | None = None,
        jwks_uri: str | None = None,
        discovery_endpoint: str | None = None,
        use_pkce: bool | None = None,
        override_user_info_on_sign_in: bool | None = None,
        skip_discovery: bool = False,
    ) -> ProviderT:
        provider = await self._get_provider_or_404(provider_id)
        self._assert_provider_type(provider, expected_type="oidc")
        await self._require_provider_access(provider)
        existing_config = self._provider_oidc_config(provider)

        config = await self._resolve_oidc_config(
            issuer=issuer or provider.issuer,
            client_id=(client_id or existing_config.client_id).strip(),
            client_secret=(client_secret or existing_config.client_secret).strip(),
            scopes=scopes or list(existing_config.scopes),
            token_endpoint_auth_method=token_endpoint_auth_method or existing_config.token_endpoint_auth_method,
            claim_mapping=claim_mapping or existing_config.claim_mapping,
            authorization_endpoint=authorization_endpoint or existing_config.authorization_endpoint,
            token_endpoint=token_endpoint or existing_config.token_endpoint,
            userinfo_endpoint=userinfo_endpoint or existing_config.userinfo_endpoint,
            jwks_uri=jwks_uri or existing_config.jwks_uri,
            discovery_endpoint=discovery_endpoint or existing_config.discovery_endpoint,
            use_pkce=existing_config.use_pkce if use_pkce is None else use_pkce,
            override_user_info_on_sign_in=(
                existing_config.override_user_info_on_sign_in
                if override_user_info_on_sign_in is None
                else override_user_info_on_sign_in
            ),
            skip_discovery=skip_discovery,
        )

        updated_provider = await self.settings.adapter.update_provider(
            self.client.db,
            sso_provider_id=provider.id,
            issuer=config.issuer,
            oidc_config=serialize_oidc_config(config),
            saml_config=None,
        )
        if updated_provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )

        if domains is not None:
            normalized_domains = self._normalize_domains(domains)
            await self._ensure_domains_are_available(normalized_domains, sso_provider_id=provider.id)
            await self._sync_provider_domains(provider=provider, domains=normalized_domains)

        return updated_provider

    async def register_saml_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str,
        entity_id: str,
        sso_url: str,
        x509_certificate: str,
        domains: list[str] | None = None,
        organization_id: UUID | None = None,
        slo_url: str | None = None,
        name_id_format: str | None = None,
        binding: str = "redirect",
        allow_idp_initiated: bool = False,
        want_assertions_signed: bool = True,
        sign_authn_request: bool = True,
        signature_algorithm: str = "rsa-sha256",
        digest_algorithm: str = "sha256",
    ) -> ProviderT:
        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        if await self.settings.adapter.get_provider_by_provider_id(self.client.db, provider_id=normalized_provider_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id already exists",
            )

        await self._require_registration_access(organization_id=organization_id)
        await self._ensure_provider_capacity(organization_id=organization_id)
        normalized_domains = self._normalize_domains(domains)
        await self._ensure_domains_are_available(normalized_domains)

        provider = await self.settings.adapter.create_provider(
            self.client.db,
            organization_id=organization_id,
            created_by_individual_id=None if organization_id else self._current_individual_or_403().id,
            provider_type="saml",
            provider_id=normalized_provider_id,
            issuer=normalize_issuer(issuer),
            oidc_config=None,
            saml_config=serialize_saml_config(
                SAMLProviderConfig(
                    entity_id=entity_id.strip(),
                    sso_url=sso_url.strip(),
                    x509_certificate=x509_certificate.strip(),
                    slo_url=slo_url.strip() if slo_url else None,
                    name_id_format=name_id_format.strip() if name_id_format else None,
                    binding=binding.strip(),
                    allow_idp_initiated=allow_idp_initiated,
                    want_assertions_signed=want_assertions_signed,
                    sign_authn_request=sign_authn_request,
                    signature_algorithm=signature_algorithm.strip(),
                    digest_algorithm=digest_algorithm.strip(),
                ),
            ),
        )
        try:
            await self._sync_provider_domains(provider=provider, domains=normalized_domains)
        except Exception:
            await self.settings.adapter.delete_provider(self.client.db, sso_provider_id=provider.id)
            raise
        return provider

    async def update_saml_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str | None = None,
        entity_id: str | None = None,
        sso_url: str | None = None,
        x509_certificate: str | None = None,
        domains: list[str] | None = None,
        slo_url: str | None = None,
        name_id_format: str | None = None,
        binding: str | None = None,
        allow_idp_initiated: bool | None = None,
        want_assertions_signed: bool | None = None,
        sign_authn_request: bool | None = None,
        signature_algorithm: str | None = None,
        digest_algorithm: str | None = None,
    ) -> ProviderT:
        provider = await self._get_provider_or_404(provider_id)
        self._assert_provider_type(provider, expected_type="saml")
        await self._require_provider_access(provider)
        existing_config = self._provider_saml_config(provider)

        updated_provider = await self.settings.adapter.update_provider(
            self.client.db,
            sso_provider_id=provider.id,
            issuer=normalize_issuer(issuer or provider.issuer),
            oidc_config=None,
            saml_config=serialize_saml_config(
                SAMLProviderConfig(
                    entity_id=(entity_id or existing_config.entity_id).strip(),
                    sso_url=(sso_url or existing_config.sso_url).strip(),
                    x509_certificate=(x509_certificate or existing_config.x509_certificate).strip(),
                    slo_url=(slo_url or existing_config.slo_url).strip()
                    if (slo_url or existing_config.slo_url)
                    else None,
                    name_id_format=(name_id_format or existing_config.name_id_format).strip()
                    if (name_id_format or existing_config.name_id_format)
                    else None,
                    binding=(binding or existing_config.binding).strip(),
                    allow_idp_initiated=(
                        existing_config.allow_idp_initiated if allow_idp_initiated is None else allow_idp_initiated
                    ),
                    want_assertions_signed=(
                        existing_config.want_assertions_signed
                        if want_assertions_signed is None
                        else want_assertions_signed
                    ),
                    sign_authn_request=(
                        existing_config.sign_authn_request if sign_authn_request is None else sign_authn_request
                    ),
                    signature_algorithm=(signature_algorithm or existing_config.signature_algorithm).strip(),
                    digest_algorithm=(digest_algorithm or existing_config.digest_algorithm).strip(),
                    claim_mapping=existing_config.claim_mapping,
                ),
            ),
        )
        if updated_provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )

        if domains is not None:
            normalized_domains = self._normalize_domains(domains)
            await self._ensure_domains_are_available(normalized_domains, sso_provider_id=provider.id)
            await self._sync_provider_domains(provider=provider, domains=normalized_domains)

        return updated_provider

    async def delete_provider(self, *, provider_id: str) -> bool:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_provider_access(provider)
        return await self.settings.adapter.delete_provider(self.client.db, sso_provider_id=provider.id)

    async def get_provider(self, *, provider_id: str) -> ProviderT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_provider_access(provider)
        return provider

    async def get_provider_summary(self, *, provider_id: str) -> SSOProviderSummary:
        provider = await self.get_provider(provider_id=provider_id)
        return await self._build_provider_summary(provider)

    async def list_providers(self, *, organization_id: UUID | None = None) -> list[ProviderT]:
        if organization_id is not None:
            await self._require_org_admin(organization_id=organization_id)
            return await self.settings.adapter.list_providers_for_organization(
                self.client.db,
                organization_id=organization_id,
            )

        current_individual = self._current_individual_or_403()
        return await self.settings.adapter.list_providers_for_individual(
            self.client.db,
            individual_id=current_individual.id,
        )

    async def list_provider_summaries(self, *, organization_id: UUID | None = None) -> list[SSOProviderSummary]:
        providers = await self.list_providers(organization_id=organization_id)
        return [await self._build_provider_summary(provider) for provider in providers]

    async def create_domain_challenge(self, *, provider_id: str, domain: str) -> SSODomainChallenge:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_provider_access(provider)

        normalized_domain = normalize_domain(domain)
        existing = await self.settings.adapter.get_domain_by_name(self.client.db, domain=normalized_domain)
        verification_token = self._generate_verification_token()
        if existing is None:
            sso_domain = await self.settings.adapter.create_domain(
                self.client.db,
                sso_provider_id=provider.id,
                domain=normalized_domain,
                verification_token=verification_token,
            )
        else:
            if existing.sso_provider_id != provider.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="domain is already registered to another provider",
                )
            updated = await self.settings.adapter.update_domain(
                self.client.db,
                domain_id=existing.id,
                verification_token=verification_token,
                verified_at=None,
            )
            if updated is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="domain not found",
                )
            sso_domain = updated

        return self._build_domain_challenge(provider=provider, sso_domain=sso_domain)

    async def verify_domain(self, *, provider_id: str, domain: str) -> DomainT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_provider_access(provider)

        normalized_domain = normalize_domain(domain)
        sso_domain = await self.settings.adapter.get_domain_by_name(self.client.db, domain=normalized_domain)
        if sso_domain is None or sso_domain.sso_provider_id != provider.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="domain not found for provider",
            )

        challenge = self._build_domain_challenge(provider=provider, sso_domain=sso_domain)
        records = await lookup_txt_records(challenge.record_name)
        if challenge.record_value not in records:
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

    async def _build_provider_summary(self, provider: ProviderT) -> SSOProviderSummary:
        domains = await self.settings.adapter.list_domains_for_provider(self.client.db, sso_provider_id=provider.id)
        verified_domains = tuple(sorted(domain.domain for domain in domains if domain.verified_at is not None))
        client_id: str | None = None
        if provider.provider_type == "oidc":
            client_id = mask_client_id(self._provider_oidc_config(provider).client_id)
        return SSOProviderSummary(
            id=provider.id,
            provider_id=provider.provider_id,
            provider_type=provider.provider_type,
            issuer=provider.issuer,
            organization_id=provider.organization_id,
            created_by_individual_id=provider.created_by_individual_id,
            client_id=client_id,
            domain_verified=bool(verified_domains),
            domains=tuple(sorted(domain.domain for domain in domains)),
            verified_domains=verified_domains,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )

    async def _resolve_oidc_config(  # noqa: PLR0913
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        scopes: list[str] | None,
        token_endpoint_auth_method: str,
        claim_mapping: OIDCClaimMapping | None,
        authorization_endpoint: str | None,
        token_endpoint: str | None,
        userinfo_endpoint: str | None,
        jwks_uri: str | None,
        discovery_endpoint: str | None,
        use_pkce: bool,
        override_user_info_on_sign_in: bool,
        skip_discovery: bool,
    ) -> OIDCProviderConfig:
        normalized_issuer = normalize_issuer(issuer)
        normalized_client_id = client_id.strip()
        normalized_client_secret = client_secret.strip()
        resolved_scopes = scopes or self.settings.default_scopes
        resolved_claim_mapping = claim_mapping or OIDCClaimMapping()
        normalized_discovery_endpoint = discovery_endpoint.strip() if discovery_endpoint else None

        if not skip_discovery:
            discovery = await discover_oidc_configuration(
                issuer=normalized_issuer,
                client_id=normalized_client_id,
                client_secret=normalized_client_secret,
                scopes=resolved_scopes,
                token_endpoint_auth_method=token_endpoint_auth_method,
                claim_mapping=resolved_claim_mapping,
                timeout_seconds=self.settings.discovery_timeout_seconds,
                discovery_endpoint=normalized_discovery_endpoint,
                use_pkce=use_pkce,
                override_user_info_on_sign_in=override_user_info_on_sign_in,
            )
            return OIDCProviderConfig(
                issuer=discovery.issuer,
                client_id=discovery.config.client_id,
                client_secret=discovery.config.client_secret,
                authorization_endpoint=authorization_endpoint or discovery.config.authorization_endpoint,
                token_endpoint=token_endpoint or discovery.config.token_endpoint,
                userinfo_endpoint=userinfo_endpoint or discovery.config.userinfo_endpoint,
                discovery_endpoint=discovery.config.discovery_endpoint,
                jwks_uri=jwks_uri or discovery.config.jwks_uri,
                scopes=discovery.config.scopes,
                token_endpoint_auth_method=discovery.config.token_endpoint_auth_method,
                use_pkce=discovery.config.use_pkce,
                override_user_info_on_sign_in=discovery.config.override_user_info_on_sign_in,
                claim_mapping=discovery.config.claim_mapping,
            )

        return OIDCProviderConfig(
            issuer=normalized_issuer,
            client_id=normalized_client_id,
            client_secret=normalized_client_secret,
            authorization_endpoint=authorization_endpoint.strip() if authorization_endpoint else None,
            token_endpoint=token_endpoint.strip() if token_endpoint else None,
            userinfo_endpoint=userinfo_endpoint.strip() if userinfo_endpoint else None,
            discovery_endpoint=normalized_discovery_endpoint,
            jwks_uri=jwks_uri.strip() if jwks_uri else None,
            scopes=tuple(resolved_scopes),
            token_endpoint_auth_method=token_endpoint_auth_method,
            use_pkce=use_pkce,
            override_user_info_on_sign_in=override_user_info_on_sign_in,
            claim_mapping=resolved_claim_mapping,
        )

    async def _sync_provider_domains(self, *, provider: ProviderT, domains: list[str]) -> None:
        existing_domains = await self.settings.adapter.list_domains_for_provider(
            self.client.db,
            sso_provider_id=provider.id,
        )
        existing_by_name = {domain.domain: domain for domain in existing_domains}
        desired_domains = set(domains)
        for sso_domain in existing_domains:
            if sso_domain.domain not in desired_domains:
                await self.settings.adapter.delete_domain(self.client.db, domain_id=sso_domain.id)
        for domain in domains:
            if domain in existing_by_name:
                continue
            await self.settings.adapter.create_domain(
                self.client.db,
                sso_provider_id=provider.id,
                domain=domain,
                verification_token=self._generate_verification_token(),
            )

    def _assert_provider_type(self, provider: ProviderT, *, expected_type: str) -> None:
        if provider.provider_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"provider '{provider.provider_id}' is not a {expected_type} provider",
            )

    def _build_domain_challenge(self, *, provider: ProviderT, sso_domain: DomainT) -> SSODomainChallenge:
        record_name = build_domain_verification_record_name(
            domain=sso_domain.domain,
            provider_id=provider.provider_id,
            token_prefix=self.settings.domain_txt_prefix,
        )
        if len(record_name.split(".", maxsplit=1)[0]) > _DNS_LABEL_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="domain verification record label exceeds DNS limits",
            )
        return SSODomainChallenge(
            domain=sso_domain.domain,
            record_name=record_name,
            record_value=build_domain_verification_record_value(
                provider_id=provider.provider_id,
                token_prefix=self.settings.domain_txt_prefix,
                verification_token=sso_domain.verification_token,
            ),
            verification_token=sso_domain.verification_token,
            verified_at=sso_domain.verified_at,
        )

    def _provider_oidc_config(self, provider: ProviderT) -> OIDCProviderConfig:
        if provider.oidc_config is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider is missing oidc config",
            )
        return deserialize_oidc_config(provider.oidc_config)

    def _provider_saml_config(self, provider: ProviderT) -> SAMLProviderConfig:
        if provider.saml_config is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider is missing saml config",
            )
        from belgie_sso.utils import deserialize_saml_config  # noqa: PLC0415

        return deserialize_saml_config(provider.saml_config)

    async def _require_registration_access(self, *, organization_id: UUID | None) -> None:
        if organization_id is not None:
            if self.organization_adapter is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization support is not enabled",
                )
            if await self.organization_adapter.get_organization_by_id(self.client.db, organization_id) is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="organization not found",
                )
            await self._require_org_admin(organization_id=organization_id)
            return

        self._current_individual_or_403()

    async def _require_provider_access(self, provider: ProviderT) -> None:
        if provider.organization_id is not None:
            await self._require_org_admin(organization_id=provider.organization_id)
            return

        current_individual = self._current_individual_or_403()
        if provider.created_by_individual_id != current_individual.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="provider owner access is required",
            )

    async def _require_org_admin(self, *, organization_id: UUID) -> None:
        if self.organization_adapter is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization support is not enabled",
            )

        member = await self.organization_adapter.get_member(
            self.client.db,
            organization_id=organization_id,
            individual_id=self._current_individual_or_403().id,
        )
        if member is None or not has_any_role(member.role, ["owner", "admin"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization admin access is required",
            )

    async def _ensure_provider_capacity(self, *, organization_id: UUID | None) -> None:
        if self.settings.providers_limit is None:
            return

        existing_providers = await self.list_providers(organization_id=organization_id)
        if len(existing_providers) >= self.settings.providers_limit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider limit reached",
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

    def _normalize_domains(self, domains: list[str] | None) -> list[str]:
        if not domains:
            return []

        normalized: list[str] = []
        for domain in domains:
            value = normalize_domain(domain)
            if value in normalized:
                continue
            normalized.append(value)
        return normalized

    def _current_individual_or_403(self) -> IndividualProtocol[str]:
        if self.current_individual is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="authenticated individual is required",
            )
        return self.current_individual

    def _generate_verification_token(self) -> str:
        return secrets.token_urlsafe(24)
