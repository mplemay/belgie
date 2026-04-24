from __future__ import annotations

import inspect
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from belgie_organization.roles import has_any_role
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.sso import (
    DomainVerificationState,
    OIDCClaimMapping,
    OIDCProviderConfig,
    SAMLClaimMapping,
    SAMLProviderConfig,
    SSOProviderProtocol,
)
from fastapi import HTTPException, status

from belgie_sso.discovery import DiscoveryError, discover_oidc_configuration, select_token_endpoint_auth_method
from belgie_sso.dns import DNSTxtLookupError, lookup_txt_records
from belgie_sso.models import SSODomainChallenge, SSOProviderDetail, SSOProviderSummary
from belgie_sso.saml_algorithms import validate_config_digest_algorithm, validate_config_signature_algorithm
from belgie_sso.utils import (
    build_domain_verification_record_name,
    build_domain_verification_record_value,
    build_provider_callback_url,
    build_shared_callback_url,
    deserialize_oidc_config,
    fingerprint_certificate,
    mask_client_id,
    normalize_http_url,
    normalize_issuer,
    normalize_provider_domain_value,
    normalize_provider_id,
    serialize_oidc_config,
    serialize_saml_config,
    split_provider_domains,
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
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
]:
    client: BelgieClient
    base_url: str
    settings: EnterpriseSSO[ProviderT]
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT] | None = None
    current_individual: IndividualProtocol[str] | None = None

    async def register_oidc_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        domain: str | None = None,
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
        override_user_info_on_sign_in: bool | None = None,
        skip_discovery: bool = False,
    ) -> ProviderT:
        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        if domain is None and domains is not None:
            domain = ",".join(domains)
        if await self.settings.adapter.get_provider_by_provider_id(self.client.db, provider_id=normalized_provider_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id already exists",
            )

        await self._require_registration_access(organization_id=organization_id)
        await self._ensure_provider_capacity(organization_id=organization_id)
        normalized_domain = self._normalize_provider_domain_or_400(domain)
        await self._ensure_domain_is_available(normalized_domain)

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

        return await self.settings.adapter.create_provider(
            self.client.db,
            organization_id=organization_id,
            created_by_individual_id=self._current_individual_or_403().id,
            provider_type="oidc",
            provider_id=normalized_provider_id,
            issuer=config.issuer,
            domain=normalized_domain,
            domain_verification=self._new_domain_verification_state(normalized_domain),
            oidc_config=serialize_oidc_config(config),
            saml_config=None,
        )

    async def update_oidc_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        domain: str | None = None,
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
        self._require_any_oidc_update_field(
            issuer=issuer,
            client_id=client_id,
            client_secret=client_secret,
            domain=domain if domain is not None else ",".join(domains) if domains is not None else None,
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
        )
        provider = await self._get_provider_or_404(provider_id)
        self._assert_provider_type(provider, expected_type="oidc")
        await self._require_provider_access(provider)
        existing_config = self._provider_oidc_config(provider)
        refresh_discovered_endpoints = not skip_discovery and (issuer is not None or discovery_endpoint is not None)
        if domain is None and domains is not None:
            domain = ",".join(domains)
        normalized_domain = self._normalize_provider_domain_or_400(domain) if domain is not None else None
        if normalized_domain is not None:
            await self._ensure_domain_is_available(normalized_domain, sso_provider_id=provider.id)

        config = await self._resolve_oidc_config(
            issuer=issuer or provider.issuer,
            client_id=(client_id or existing_config.client_id).strip(),
            client_secret=(client_secret or existing_config.client_secret).strip(),
            scopes=scopes or list(existing_config.scopes),
            token_endpoint_auth_method=token_endpoint_auth_method or existing_config.token_endpoint_auth_method,
            claim_mapping=claim_mapping or existing_config.claim_mapping,
            authorization_endpoint=(
                authorization_endpoint
                if authorization_endpoint is not None
                else None
                if refresh_discovered_endpoints
                else existing_config.authorization_endpoint
            ),
            token_endpoint=(
                token_endpoint
                if token_endpoint is not None
                else None
                if refresh_discovered_endpoints
                else existing_config.token_endpoint
            ),
            userinfo_endpoint=(
                userinfo_endpoint
                if userinfo_endpoint is not None
                else None
                if refresh_discovered_endpoints
                else existing_config.userinfo_endpoint
            ),
            jwks_uri=(
                jwks_uri if jwks_uri is not None else None if refresh_discovered_endpoints else existing_config.jwks_uri
            ),
            discovery_endpoint=(
                discovery_endpoint
                if discovery_endpoint is not None
                else None
                if refresh_discovered_endpoints
                else existing_config.discovery_endpoint
            ),
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
            domain=normalized_domain,
            domain_verification=(
                self._updated_domain_verification_state(provider=provider, domain=normalized_domain)
                if normalized_domain is not None
                else None
            ),
            oidc_config=serialize_oidc_config(config),
            saml_config=None,
        )
        if updated_provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
        return updated_provider

    async def register_saml_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str,
        entity_id: str,
        sso_url: str | None = None,
        x509_certificate: str | None = None,
        domain: str | None = None,
        domains: list[str] | None = None,
        organization_id: UUID | None = None,
        slo_url: str | None = None,
        audience: str | None = None,
        idp_metadata_xml: str | None = None,
        sp_metadata_xml: str | None = None,
        name_id_format: str | None = None,
        binding: str = "redirect",
        allow_idp_initiated: bool = True,
        want_assertions_signed: bool = True,
        sign_authn_request: bool = True,
        signature_algorithm: str = "rsa-sha256",
        digest_algorithm: str = "sha256",
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        signing_certificate: str | None = None,
        decryption_private_key: str | None = None,
        decryption_private_key_passphrase: str | None = None,
        claim_mapping: SAMLClaimMapping | None = None,
    ) -> ProviderT:
        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        if domain is None and domains is not None:
            domain = ",".join(domains)
        if await self.settings.adapter.get_provider_by_provider_id(self.client.db, provider_id=normalized_provider_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id already exists",
            )

        await self._require_registration_access(organization_id=organization_id)
        await self._ensure_provider_capacity(organization_id=organization_id)
        normalized_domain = self._normalize_provider_domain_or_400(domain)
        await self._ensure_domain_is_available(normalized_domain)
        config = self._build_saml_config(
            entity_id=entity_id,
            sso_url=sso_url,
            x509_certificate=x509_certificate,
            slo_url=slo_url,
            audience=audience,
            idp_metadata_xml=idp_metadata_xml,
            sp_metadata_xml=sp_metadata_xml,
            name_id_format=name_id_format,
            binding=binding,
            allow_idp_initiated=allow_idp_initiated,
            want_assertions_signed=want_assertions_signed,
            sign_authn_request=sign_authn_request,
            signature_algorithm=signature_algorithm,
            digest_algorithm=digest_algorithm,
            private_key=private_key,
            private_key_passphrase=private_key_passphrase,
            signing_certificate=signing_certificate,
            decryption_private_key=decryption_private_key,
            decryption_private_key_passphrase=decryption_private_key_passphrase,
            claim_mapping=claim_mapping or SAMLClaimMapping(),
        )

        return await self.settings.adapter.create_provider(
            self.client.db,
            organization_id=organization_id,
            created_by_individual_id=self._current_individual_or_403().id,
            provider_type="saml",
            provider_id=normalized_provider_id,
            issuer=normalize_issuer(issuer),
            domain=normalized_domain,
            domain_verification=self._new_domain_verification_state(normalized_domain),
            oidc_config=None,
            saml_config=serialize_saml_config(config),
        )

    async def update_saml_provider(  # noqa: PLR0913
        self,
        *,
        provider_id: str,
        issuer: str | None = None,
        entity_id: str | None = None,
        sso_url: str | None = None,
        x509_certificate: str | None = None,
        domain: str | None = None,
        domains: list[str] | None = None,
        slo_url: str | None = None,
        audience: str | None = None,
        idp_metadata_xml: str | None = None,
        sp_metadata_xml: str | None = None,
        name_id_format: str | None = None,
        binding: str | None = None,
        allow_idp_initiated: bool | None = None,
        want_assertions_signed: bool | None = None,
        sign_authn_request: bool | None = None,
        signature_algorithm: str | None = None,
        digest_algorithm: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        signing_certificate: str | None = None,
        decryption_private_key: str | None = None,
        decryption_private_key_passphrase: str | None = None,
        claim_mapping: SAMLClaimMapping | None = None,
    ) -> ProviderT:
        self._require_any_saml_update_field(
            issuer=issuer,
            entity_id=entity_id,
            sso_url=sso_url,
            x509_certificate=x509_certificate,
            domain=domain if domain is not None else ",".join(domains) if domains is not None else None,
            slo_url=slo_url,
            audience=audience,
            idp_metadata_xml=idp_metadata_xml,
            sp_metadata_xml=sp_metadata_xml,
            name_id_format=name_id_format,
            binding=binding,
            allow_idp_initiated=allow_idp_initiated,
            want_assertions_signed=want_assertions_signed,
            sign_authn_request=sign_authn_request,
            signature_algorithm=signature_algorithm,
            digest_algorithm=digest_algorithm,
            private_key=private_key,
            private_key_passphrase=private_key_passphrase,
            signing_certificate=signing_certificate,
            decryption_private_key=decryption_private_key,
            decryption_private_key_passphrase=decryption_private_key_passphrase,
            claim_mapping=claim_mapping,
        )
        provider = await self._get_provider_or_404(provider_id)
        self._assert_provider_type(provider, expected_type="saml")
        await self._require_provider_access(provider)
        existing_config = self._provider_saml_config(provider)
        if domain is None and domains is not None:
            domain = ",".join(domains)
        normalized_domain = self._normalize_provider_domain_or_400(domain) if domain is not None else None
        if normalized_domain is not None:
            await self._ensure_domain_is_available(normalized_domain, sso_provider_id=provider.id)
        config = self._build_saml_config(
            entity_id=existing_config.entity_id if entity_id is None else entity_id,
            sso_url=existing_config.sso_url if sso_url is None else sso_url,
            x509_certificate=existing_config.x509_certificate if x509_certificate is None else x509_certificate,
            slo_url=existing_config.slo_url if slo_url is None else slo_url,
            audience=existing_config.audience if audience is None else audience,
            idp_metadata_xml=existing_config.idp_metadata_xml if idp_metadata_xml is None else idp_metadata_xml,
            sp_metadata_xml=existing_config.sp_metadata_xml if sp_metadata_xml is None else sp_metadata_xml,
            name_id_format=existing_config.name_id_format if name_id_format is None else name_id_format,
            binding=existing_config.binding if binding is None else binding,
            allow_idp_initiated=(
                existing_config.allow_idp_initiated if allow_idp_initiated is None else allow_idp_initiated
            ),
            want_assertions_signed=(
                existing_config.want_assertions_signed if want_assertions_signed is None else want_assertions_signed
            ),
            sign_authn_request=(
                existing_config.sign_authn_request if sign_authn_request is None else sign_authn_request
            ),
            signature_algorithm=(
                existing_config.signature_algorithm if signature_algorithm is None else signature_algorithm
            ),
            digest_algorithm=existing_config.digest_algorithm if digest_algorithm is None else digest_algorithm,
            private_key=existing_config.private_key if private_key is None else private_key,
            private_key_passphrase=(
                existing_config.private_key_passphrase if private_key_passphrase is None else private_key_passphrase
            ),
            signing_certificate=existing_config.signing_certificate
            if signing_certificate is None
            else signing_certificate,
            decryption_private_key=(
                existing_config.decryption_private_key if decryption_private_key is None else decryption_private_key
            ),
            decryption_private_key_passphrase=(
                existing_config.decryption_private_key_passphrase
                if decryption_private_key_passphrase is None
                else decryption_private_key_passphrase
            ),
            claim_mapping=claim_mapping or existing_config.claim_mapping,
        )

        updated_provider = await self.settings.adapter.update_provider(
            self.client.db,
            sso_provider_id=provider.id,
            issuer=normalize_issuer(issuer or provider.issuer),
            domain=normalized_domain,
            domain_verification=(
                self._updated_domain_verification_state(provider=provider, domain=normalized_domain)
                if normalized_domain is not None
                else None
            ),
            oidc_config=None,
            saml_config=serialize_saml_config(config),
        )
        if updated_provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
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

    async def get_provider_detail(self, *, provider_id: str) -> SSOProviderDetail:
        provider = await self.get_provider(provider_id=provider_id)
        return await self._build_provider_detail(provider)

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

    async def list_provider_details(self, *, organization_id: UUID | None = None) -> list[SSOProviderDetail]:
        providers = await self.list_providers(organization_id=organization_id)
        return [await self._build_provider_detail(provider) for provider in providers]

    async def create_domain_challenge(self, *, provider_id: str, domain: str | None = None) -> SSODomainChallenge:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_provider_domain_access(provider)

        normalized_domain = self._require_single_domain_or_400(provider)
        if domain is not None and self._normalize_provider_domain_or_400(domain) != normalized_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="domain not found for provider",
            )
        if provider.domain_verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="domain is already verified",
            )
        if self._domain_challenge_is_active(provider):
            challenge_provider = provider
        else:
            updated = await self.settings.adapter.update_provider(
                self.client.db,
                sso_provider_id=provider.id,
                domain_verification=self._new_domain_verification_state(normalized_domain, force=True),
            )
            if updated is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="provider not found",
                )
            challenge_provider = updated
        return self._build_domain_challenge(provider=challenge_provider)

    async def verify_domain(self, *, provider_id: str, domain: str | None = None) -> ProviderT:
        provider = await self._get_provider_or_404(provider_id)
        await self._require_provider_domain_access(provider)

        normalized_domain = self._require_single_domain_or_400(provider)
        if domain is not None and self._normalize_provider_domain_or_400(domain) != normalized_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="domain not found for provider",
            )
        if provider.domain_verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="domain is already verified",
            )
        if (
            provider.domain_verification_token_expires_at is None
            or provider.domain_verification_token_expires_at <= datetime.now(UTC)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="pending domain verification challenge not found",
            )

        challenge = self._build_domain_challenge(provider=provider)
        try:
            records = await lookup_txt_records(challenge.record_name)
        except DNSTxtLookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        if challenge.record_value not in records:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="verification token not found in DNS TXT records",
            )

        verified_provider = await self.settings.adapter.update_provider(
            self.client.db,
            sso_provider_id=provider.id,
            domain_verification=DomainVerificationState(
                verified=True,
                token=None,
                token_expires_at=None,
            ),
        )
        if verified_provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
        return verified_provider

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
            domain=provider.domain,
            domain_verified=provider.domain_verified,
            callback_url=self._provider_callback_url(provider),
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )

    async def _build_provider_detail(self, provider: ProviderT) -> SSOProviderDetail:
        if provider.provider_type == "oidc":
            config = self._provider_oidc_config(provider)
            detail_config: dict[str, object] = {
                "client_id": mask_client_id(config.client_id),
                "authorization_endpoint": config.authorization_endpoint,
                "token_endpoint": config.token_endpoint,
                "userinfo_endpoint": config.userinfo_endpoint,
                "discovery_endpoint": config.discovery_endpoint,
                "jwks_uri": config.jwks_uri,
                "scopes": list(config.scopes),
                "token_endpoint_auth_method": config.token_endpoint_auth_method,
                "use_pkce": config.use_pkce,
                "override_user_info_on_sign_in": config.override_user_info_on_sign_in,
                "claim_mapping": {
                    "subject": config.claim_mapping.subject,
                    "email": config.claim_mapping.email,
                    "email_verified": config.claim_mapping.email_verified,
                    "name": config.claim_mapping.name,
                    "image": config.claim_mapping.image,
                    "extra_fields": dict(config.claim_mapping.extra_fields),
                },
            }
        else:
            config = self._provider_saml_config(provider)
            detail_config = {
                "entity_id": config.entity_id,
                "sso_url": config.sso_url,
                "slo_url": config.slo_url,
                "audience": config.audience,
                "idp_metadata_xml_present": bool(config.idp_metadata_xml),
                "sp_metadata_xml_present": bool(config.sp_metadata_xml),
                "name_id_format": config.name_id_format,
                "binding": config.binding,
                "allow_idp_initiated": config.allow_idp_initiated,
                "want_assertions_signed": config.want_assertions_signed,
                "sign_authn_request": config.sign_authn_request,
                "signature_algorithm": config.signature_algorithm,
                "digest_algorithm": config.digest_algorithm,
                "x509_certificate_present": bool(config.x509_certificate),
                "x509_certificate_fingerprint": fingerprint_certificate(config.x509_certificate),
                "private_key_present": bool(config.private_key),
                "private_key_passphrase_present": bool(config.private_key_passphrase),
                "signing_certificate_present": bool(config.signing_certificate),
                "signing_certificate_fingerprint": fingerprint_certificate(config.signing_certificate),
                "decryption_private_key_present": bool(config.decryption_private_key),
                "decryption_private_key_passphrase_present": bool(config.decryption_private_key_passphrase),
                "claim_mapping": {
                    "subject": config.claim_mapping.subject,
                    "email": config.claim_mapping.email,
                    "email_verified": config.claim_mapping.email_verified,
                    "name": config.claim_mapping.name,
                    "first_name": config.claim_mapping.first_name,
                    "last_name": config.claim_mapping.last_name,
                    "groups": config.claim_mapping.groups,
                    "extra_fields": dict(config.claim_mapping.extra_fields),
                },
            }
        return SSOProviderDetail(
            id=provider.id,
            provider_id=provider.provider_id,
            provider_type=provider.provider_type,
            issuer=provider.issuer,
            organization_id=provider.organization_id,
            created_by_individual_id=provider.created_by_individual_id,
            domain=provider.domain,
            domain_verified=provider.domain_verified,
            callback_url=self._provider_callback_url(provider),
            domain_challenge=self._domain_challenge_or_none(provider),
            config=detail_config,
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
        override_user_info_on_sign_in: bool | None,
        skip_discovery: bool,
    ) -> OIDCProviderConfig:
        normalized_token_endpoint_auth_method = token_endpoint_auth_method.strip()
        self._validate_oidc_token_endpoint_auth_method_or_400(normalized_token_endpoint_auth_method)
        normalized_issuer = normalize_issuer(issuer)
        normalized_client_id = client_id.strip()
        normalized_client_secret = client_secret.strip()
        resolved_scopes = scopes or self.settings.default_scopes
        resolved_claim_mapping = claim_mapping or OIDCClaimMapping()
        normalized_discovery_endpoint = discovery_endpoint.strip() if discovery_endpoint else None
        resolved_override_user_info_on_sign_in = (
            self.settings.default_override_user_info_on_sign_in
            if override_user_info_on_sign_in is None
            else override_user_info_on_sign_in
        )

        if not skip_discovery:
            try:
                discovery = await discover_oidc_configuration(
                    issuer=normalized_issuer,
                    client_id=normalized_client_id,
                    client_secret=normalized_client_secret,
                    scopes=resolved_scopes,
                    token_endpoint_auth_method=normalized_token_endpoint_auth_method,
                    claim_mapping=resolved_claim_mapping,
                    timeout_seconds=self.settings.discovery_timeout_seconds,
                    discovery_endpoint=normalized_discovery_endpoint,
                    trusted_origins=self.settings.trusted_idp_origins,
                    use_pkce=use_pkce,
                    override_user_info_on_sign_in=resolved_override_user_info_on_sign_in,
                )
            except DiscoveryError as exc:
                self._raise_discovery_http_exception(exc)
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
            token_endpoint_auth_method=normalized_token_endpoint_auth_method,
            use_pkce=use_pkce,
            override_user_info_on_sign_in=resolved_override_user_info_on_sign_in,
            claim_mapping=resolved_claim_mapping,
        )

    def _assert_provider_type(self, provider: ProviderT, *, expected_type: str) -> None:
        if provider.provider_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"provider '{provider.provider_id}' is not a {expected_type} provider",
            )

    def _build_domain_challenge(self, *, provider: ProviderT) -> SSODomainChallenge:
        domain = self._require_single_domain_or_400(provider)
        verification_token = provider.domain_verification_token
        if verification_token is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="pending domain verification challenge not found",
            )
        record_name = build_domain_verification_record_name(
            domain=domain,
            provider_id=provider.provider_id,
            token_prefix=self.settings.domain_txt_prefix,
        )
        if len(record_name.split(".", maxsplit=1)[0]) > _DNS_LABEL_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="domain verification record label exceeds DNS limits",
            )
        return SSODomainChallenge(
            domain=domain,
            record_name=record_name,
            record_value=build_domain_verification_record_value(
                provider_id=provider.provider_id,
                token_prefix=self.settings.domain_txt_prefix,
                verification_token=verification_token,
            ),
            verification_token=verification_token,
            expires_at=provider.domain_verification_token_expires_at,
            verified_at=provider.updated_at if provider.domain_verified else None,
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
            if self.organization_adapter is None:
                await self._require_provider_owner(provider)
                return
            await self._require_org_admin(organization_id=provider.organization_id)
            return

        await self._require_provider_owner(provider)

    async def _require_provider_domain_access(self, provider: ProviderT) -> None:
        await self._require_provider_owner(provider)
        if provider.organization_id is None or self.organization_adapter is None:
            return
        member = await self.organization_adapter.get_member(
            self.client.db,
            organization_id=provider.organization_id,
            individual_id=self._current_individual_or_403().id,
        )
        if member is not None:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization membership is required",
        )

    async def _require_provider_owner(self, provider: ProviderT) -> None:
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
        limit = self.settings.providers_limit
        if limit is None:
            return
        if inspect.isroutine(limit):
            resolved_limit = limit(organization_id)
            limit = await resolved_limit if inspect.isawaitable(resolved_limit) else resolved_limit
        if limit is None:
            return
        if limit == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider registration is disabled",
            )

        existing_providers = await self.list_providers(organization_id=organization_id)
        if len(existing_providers) >= limit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider limit reached",
            )

    async def _ensure_domain_is_available(
        self,
        domain_value: str,
        *,
        sso_provider_id: UUID | None = None,
    ) -> None:
        for domain in split_provider_domains(domain_value):
            if existing := await self.settings.adapter.get_provider_by_domain(self.client.db, domain=domain):
                if sso_provider_id is not None and existing.id == sso_provider_id:
                    continue
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"domain '{domain}' is already registered",
                )

    def _normalize_provider_domain_or_400(self, domain_value: str | None) -> str:
        try:
            normalized = normalize_provider_domain_value(domain_value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        if self.settings.domain_verification.enabled and len(split_provider_domains(normalized)) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="domain verification requires exactly one domain per provider",
            )
        return normalized

    def _validate_oidc_token_endpoint_auth_method_or_400(self, token_endpoint_auth_method: str) -> None:
        normalized_token_endpoint_auth_method = token_endpoint_auth_method.strip()
        try:
            select_token_endpoint_auth_method(
                requested_method=normalized_token_endpoint_auth_method,
                supported_methods=None,
            )
        except DiscoveryError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    def _require_any_oidc_update_field(  # noqa: PLR0913
        self,
        *,
        issuer: str | None,
        client_id: str | None,
        client_secret: str | None,
        domain: str | None,
        scopes: list[str] | None,
        token_endpoint_auth_method: str | None,
        claim_mapping: OIDCClaimMapping | None,
        authorization_endpoint: str | None,
        token_endpoint: str | None,
        userinfo_endpoint: str | None,
        jwks_uri: str | None,
        discovery_endpoint: str | None,
        use_pkce: bool | None,
        override_user_info_on_sign_in: bool | None,
    ) -> None:
        if any(
            value is not None
            for value in (
                issuer,
                client_id,
                client_secret,
                domain,
                scopes,
                token_endpoint_auth_method,
                claim_mapping,
                authorization_endpoint,
                token_endpoint,
                userinfo_endpoint,
                jwks_uri,
                discovery_endpoint,
                use_pkce,
                override_user_info_on_sign_in,
            )
        ):
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="at least one update field must be provided",
        )

    def _require_any_saml_update_field(  # noqa: PLR0913
        self,
        *,
        issuer: str | None,
        entity_id: str | None,
        sso_url: str | None,
        x509_certificate: str | None,
        domain: str | None,
        slo_url: str | None,
        audience: str | None,
        idp_metadata_xml: str | None,
        sp_metadata_xml: str | None,
        name_id_format: str | None,
        binding: str | None,
        allow_idp_initiated: bool | None,
        want_assertions_signed: bool | None,
        sign_authn_request: bool | None,
        signature_algorithm: str | None,
        digest_algorithm: str | None,
        private_key: str | None,
        private_key_passphrase: str | None,
        signing_certificate: str | None,
        decryption_private_key: str | None,
        decryption_private_key_passphrase: str | None,
        claim_mapping: SAMLClaimMapping | None,
    ) -> None:
        if any(
            value is not None
            for value in (
                issuer,
                entity_id,
                sso_url,
                x509_certificate,
                domain,
                slo_url,
                audience,
                idp_metadata_xml,
                sp_metadata_xml,
                name_id_format,
                binding,
                allow_idp_initiated,
                want_assertions_signed,
                sign_authn_request,
                signature_algorithm,
                digest_algorithm,
                private_key,
                private_key_passphrase,
                signing_certificate,
                decryption_private_key,
                decryption_private_key_passphrase,
                claim_mapping,
            )
        ):
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="at least one update field must be provided",
        )

    def _build_saml_config(  # noqa: PLR0913
        self,
        *,
        entity_id: str,
        sso_url: str | None,
        x509_certificate: str | None,
        slo_url: str | None,
        audience: str | None,
        idp_metadata_xml: str | None,
        sp_metadata_xml: str | None,
        name_id_format: str | None,
        binding: str,
        allow_idp_initiated: bool,
        want_assertions_signed: bool,
        sign_authn_request: bool,
        signature_algorithm: str,
        digest_algorithm: str,
        private_key: str | None,
        private_key_passphrase: str | None,
        signing_certificate: str | None,
        decryption_private_key: str | None,
        decryption_private_key_passphrase: str | None,
        claim_mapping: SAMLClaimMapping,
    ) -> SAMLProviderConfig:
        normalized_binding = binding.strip().lower()
        if normalized_binding not in {"post", "redirect"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="binding must be one of: post, redirect",
            )

        try:
            normalized_signature_algorithm = validate_config_signature_algorithm(
                signature_algorithm,
                on_deprecated=self.settings.saml.on_deprecated,
                allowed_signature_algorithms=self.settings.saml.allowed_signature_algorithms,
            )
            normalized_digest_algorithm = validate_config_digest_algorithm(
                digest_algorithm,
                on_deprecated=self.settings.saml.on_deprecated,
                allowed_digest_algorithms=self.settings.saml.allowed_digest_algorithms,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        normalized_entity_id = entity_id.strip()
        if not normalized_entity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="entity_id must be a non-empty string",
            )

        try:
            normalized_sso_url = normalize_http_url(sso_url, field_name="sso_url") if sso_url else None
            normalized_slo_url = normalize_http_url(slo_url, field_name="slo_url") if slo_url else None
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        normalized_x509_certificate = (
            x509_certificate.strip() if x509_certificate and x509_certificate.strip() else None
        )
        normalized_idp_metadata_xml = idp_metadata_xml.strip() if idp_metadata_xml else None
        if normalized_sso_url is None and normalized_idp_metadata_xml is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sso_url or idp_metadata_xml is required",
            )
        if normalized_x509_certificate is None and normalized_idp_metadata_xml is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="x509_certificate or idp_metadata_xml is required",
            )

        return SAMLProviderConfig(
            entity_id=normalized_entity_id,
            sso_url=normalized_sso_url,
            x509_certificate=normalized_x509_certificate,
            slo_url=normalized_slo_url,
            audience=audience.strip() if audience else None,
            idp_metadata_xml=normalized_idp_metadata_xml,
            sp_metadata_xml=sp_metadata_xml.strip() if sp_metadata_xml else None,
            name_id_format=name_id_format.strip() if name_id_format else None,
            binding=normalized_binding,
            allow_idp_initiated=allow_idp_initiated,
            want_assertions_signed=want_assertions_signed,
            sign_authn_request=sign_authn_request,
            signature_algorithm=normalized_signature_algorithm,
            digest_algorithm=normalized_digest_algorithm,
            private_key=private_key.strip() if private_key else None,
            private_key_passphrase=private_key_passphrase.strip() if private_key_passphrase else None,
            signing_certificate=signing_certificate.strip() if signing_certificate else None,
            decryption_private_key=decryption_private_key.strip() if decryption_private_key else None,
            decryption_private_key_passphrase=(
                decryption_private_key_passphrase.strip() if decryption_private_key_passphrase else None
            ),
            claim_mapping=claim_mapping,
        )

    def _current_individual_or_403(self) -> IndividualProtocol[str]:
        if self.current_individual is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="authenticated individual is required",
            )
        return self.current_individual

    def _generate_verification_token(self) -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def _raise_discovery_http_exception(exc: DiscoveryError) -> None:
        if exc.code == "discovery_timeout":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OIDC discovery timed out: {exc}",
            ) from exc
        if exc.code == "discovery_unexpected_error":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OIDC discovery failed: {exc}",
            ) from exc
        if exc.code == "discovery_not_found":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OIDC discovery endpoint not found: {exc}",
            ) from exc
        if exc.code == "discovery_invalid_url":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid OIDC discovery URL: {exc}",
            ) from exc
        if exc.code == "discovery_untrusted_origin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"untrusted OIDC discovery URL: {exc}",
            ) from exc
        if exc.code == "discovery_invalid_json":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OIDC discovery returned invalid data: {exc}",
            ) from exc
        if exc.code == "discovery_incomplete":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OIDC discovery document is missing required fields: {exc}",
            ) from exc
        if exc.code == "issuer_mismatch":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OIDC issuer mismatch: {exc}",
            ) from exc
        if exc.code == "unsupported_token_auth_method":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"incompatible OIDC provider: {exc}",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OIDC discovery failed: {exc}",
        ) from exc

    def _next_domain_challenge_expiration(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.settings.domain_verification.challenge_ttl_seconds)

    def _domain_challenge_is_active(self, provider: ProviderT) -> bool:
        return (
            provider.domain_verification_token_expires_at is not None
            and provider.domain_verification_token_expires_at > datetime.now(UTC)
        )

    def _require_single_domain_or_400(self, provider: ProviderT) -> str:
        domains = split_provider_domains(provider.domain)
        if len(domains) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider must have exactly one domain",
            )
        return domains[0]

    def _domain_challenge_or_none(self, provider: ProviderT) -> SSODomainChallenge | None:
        if provider.domain_verified or not provider.domain or provider.domain_verification_token is None:
            return None
        return self._build_domain_challenge(provider=provider)

    def _provider_callback_url(self, provider: ProviderT) -> str:
        if provider.provider_type == "oidc":
            return build_shared_callback_url(
                self.base_url,
                redirect_uri=self.settings.redirect_uri,
            )
        return build_provider_callback_url(self.base_url, provider_id=provider.provider_id)

    def _new_domain_verification_state(self, domain: str, *, force: bool = False) -> DomainVerificationState | None:
        if not domain:
            return DomainVerificationState(verified=False, token=None, token_expires_at=None)
        if not self.settings.domain_verification.enabled and not force:
            return DomainVerificationState(verified=False, token=None, token_expires_at=None)
        return DomainVerificationState(
            verified=False,
            token=self._generate_verification_token(),
            token_expires_at=self._next_domain_challenge_expiration(),
        )

    def _updated_domain_verification_state(
        self,
        *,
        provider: ProviderT,
        domain: str,
    ) -> DomainVerificationState:
        if domain == provider.domain:
            return DomainVerificationState(
                verified=provider.domain_verified,
                token=provider.domain_verification_token,
                token_expires_at=provider.domain_verification_token_expires_at,
            )
        return self._new_domain_verification_state(domain) or DomainVerificationState(
            verified=False,
            token=None,
            token_expires_at=None,
        )
