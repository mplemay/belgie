from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from belgie_proto.sso import DomainVerificationState, OIDCClaimMapping, OIDCProviderConfig
from belgie_sso.client import SSOClient
from belgie_sso.discovery import DiscoveryError, OIDCDiscoveryResult
from belgie_sso.dns import DNSTxtLookupError
from belgie_sso.settings import EnterpriseSSO
from belgie_sso.utils import deserialize_saml_config, split_provider_domains
from fastapi import HTTPException


@dataclass
class FakeIndividual:
    id: UUID
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str]


@dataclass
class FakeOrganization:
    id: UUID
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeMember:
    id: UUID
    organization_id: UUID
    individual_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeProvider:
    id: UUID
    organization_id: UUID | None
    created_by_individual_id: UUID | None
    provider_type: str
    provider_id: str
    issuer: str
    domain: str
    domain_verified: bool
    domain_verification_token: str | None
    domain_verification_token_expires_at: datetime | None
    oidc_config: dict[str, str | bool | list[str] | dict[str, str]] | None
    saml_config: dict[str, str | bool | list[str] | dict[str, str]] | None
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeDomain:
    id: UUID
    sso_provider_id: UUID
    domain: str
    verification_token: str
    verification_token_expires_at: datetime | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemorySSOAdapter:
    def __init__(self) -> None:
        self.providers: dict[UUID, FakeProvider] = {}
        self.domains: dict[UUID, FakeDomain] = {}

    async def create_provider(
        self,
        _session: object,
        *,
        organization_id: UUID | None,
        created_by_individual_id: UUID | None,
        provider_type: str,
        provider_id: str,
        issuer: str,
        domain: str = "",
        domain_verification: DomainVerificationState | None = None,
        oidc_config: dict[str, str | bool | list[str] | dict[str, str]] | None,
        saml_config: dict[str, str | bool | list[str] | dict[str, str]] | None,
    ) -> FakeProvider:
        now = datetime.now(UTC)
        provider = FakeProvider(
            id=uuid4(),
            organization_id=organization_id,
            created_by_individual_id=created_by_individual_id,
            provider_type=provider_type,
            provider_id=provider_id,
            issuer=issuer,
            domain=domain,
            domain_verified=domain_verification.verified if domain_verification is not None else False,
            domain_verification_token=domain_verification.token if domain_verification is not None else None,
            domain_verification_token_expires_at=domain_verification.token_expires_at
            if domain_verification is not None
            else None,
            oidc_config=oidc_config,
            saml_config=saml_config,
            created_at=now,
            updated_at=now,
        )
        self.providers[provider.id] = provider
        self._sync_domains_for_provider(provider)
        return provider

    async def get_provider_by_id(self, _session: object, *, sso_provider_id: UUID) -> FakeProvider | None:
        return self.providers.get(sso_provider_id)

    async def get_provider_by_provider_id(self, _session: object, *, provider_id: str) -> FakeProvider | None:
        return next((provider for provider in self.providers.values() if provider.provider_id == provider_id), None)

    async def get_provider_by_domain(self, _session: object, *, domain: str) -> FakeProvider | None:
        return next(
            (provider for provider in self.providers.values() if domain in split_provider_domains(provider.domain)),
            None,
        )

    async def list_providers_for_organization(self, _session: object, *, organization_id: UUID) -> list[FakeProvider]:
        return [provider for provider in self.providers.values() if provider.organization_id == organization_id]

    async def list_providers_for_individual(self, _session: object, *, individual_id: UUID) -> list[FakeProvider]:
        return [
            provider
            for provider in self.providers.values()
            if provider.created_by_individual_id == individual_id and provider.organization_id is None
        ]

    async def update_provider(
        self,
        _session: object,
        *,
        sso_provider_id: UUID,
        organization_id: UUID | None = None,
        created_by_individual_id: UUID | None = None,
        provider_type: str | None = None,
        issuer: str | None = None,
        domain: str | None = None,
        domain_verification: DomainVerificationState | None = None,
        oidc_config: dict[str, str | bool | list[str] | dict[str, str]] | None = None,
        saml_config: dict[str, str | bool | list[str] | dict[str, str]] | None = None,
    ) -> FakeProvider | None:
        provider = self.providers.get(sso_provider_id)
        if provider is None:
            return None
        if organization_id is not None:
            provider.organization_id = organization_id
        if created_by_individual_id is not None:
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
        self._sync_domains_for_provider(provider)
        return provider

    async def delete_provider(self, _session: object, *, sso_provider_id: UUID) -> bool:
        provider = self.providers.pop(sso_provider_id, None)
        if provider is None:
            return False
        for domain_id in [domain.id for domain in self.domains.values() if domain.sso_provider_id == sso_provider_id]:
            self.domains.pop(domain_id)
        return True

    async def list_providers_matching_domain(
        self,
        _session: object,
        *,
        domain: str,
        verified_only: bool,
    ) -> list[FakeProvider]:
        return [
            provider
            for provider in self.providers.values()
            if (not verified_only or provider.domain_verified)
            and any(item == domain or domain.endswith(f".{item}") for item in split_provider_domains(provider.domain))
        ]

    async def create_domain(
        self,
        _session: object,
        *,
        sso_provider_id: UUID,
        domain: str,
        verification_token: str,
        verification_token_expires_at: datetime | None = None,
    ) -> FakeDomain:
        now = datetime.now(UTC)
        sso_domain = FakeDomain(
            id=uuid4(),
            sso_provider_id=sso_provider_id,
            domain=domain,
            verification_token=verification_token,
            verification_token_expires_at=verification_token_expires_at,
            verified_at=None,
            created_at=now,
            updated_at=now,
        )
        self.domains[sso_domain.id] = sso_domain
        if (provider := self.providers.get(sso_provider_id)) is not None:
            domains = list(split_provider_domains(provider.domain))
            if domain not in domains:
                domains.append(domain)
                provider.domain = ",".join(domains)
            provider.domain_verification_token = verification_token
            provider.domain_verification_token_expires_at = verification_token_expires_at
            provider.domain_verified = False
            provider.updated_at = now
        return sso_domain

    async def get_domain(self, _session: object, *, domain_id: UUID) -> FakeDomain | None:
        return self.domains.get(domain_id)

    async def get_domain_by_name(self, _session: object, *, domain: str) -> FakeDomain | None:
        return next((item for item in self.domains.values() if item.domain == domain), None)

    async def get_verified_domain(self, _session: object, *, domain: str) -> FakeDomain | None:
        return next(
            (item for item in self.domains.values() if item.domain == domain and item.verified_at is not None),
            None,
        )

    async def list_verified_domains_matching(self, _session: object, *, domain: str) -> list[FakeDomain]:
        return [
            item
            for item in self.domains.values()
            if item.verified_at is not None and (item.domain == domain or domain.endswith(f".{item.domain}"))
        ]

    async def list_domains_matching(self, _session: object, *, domain: str) -> list[FakeDomain]:
        return [item for item in self.domains.values() if item.domain == domain or domain.endswith(f".{item.domain}")]

    async def list_domains_for_provider(self, _session: object, *, sso_provider_id: UUID) -> list[FakeDomain]:
        return [item for item in self.domains.values() if item.sso_provider_id == sso_provider_id]

    async def update_domain(
        self,
        _session: object,
        *,
        domain_id: UUID,
        verification_token: str | None = None,
        verification_token_expires_at: datetime | None = None,
        verified_at: datetime | None = None,
    ) -> FakeDomain | None:
        sso_domain = self.domains.get(domain_id)
        if sso_domain is None:
            return None
        if verification_token is not None:
            sso_domain.verification_token = verification_token
        if verification_token_expires_at is not None:
            sso_domain.verification_token_expires_at = verification_token_expires_at
        sso_domain.verified_at = verified_at
        sso_domain.updated_at = datetime.now(UTC)
        if (provider := self.providers.get(sso_domain.sso_provider_id)) is not None:
            provider.domain_verification_token = sso_domain.verification_token
            provider.domain_verification_token_expires_at = sso_domain.verification_token_expires_at
            provider.domain_verified = sso_domain.verified_at is not None
            provider.updated_at = sso_domain.updated_at
        return sso_domain

    async def delete_domain(self, _session: object, *, domain_id: UUID) -> bool:
        if domain_id not in self.domains:
            return False
        domain = self.domains.pop(domain_id)
        if (provider := self.providers.get(domain.sso_provider_id)) is not None:
            provider.domain = ",".join(
                item for item in split_provider_domains(provider.domain) if item != domain.domain
            )
            provider.domain_verified = False
            provider.domain_verification_token = None
            provider.domain_verification_token_expires_at = None
            provider.updated_at = datetime.now(UTC)
        return True

    async def delete_domains_for_provider(self, _session: object, *, sso_provider_id: UUID) -> int:
        domain_ids = [item.id for item in self.domains.values() if item.sso_provider_id == sso_provider_id]
        for domain_id in domain_ids:
            self.domains.pop(domain_id)
        if (provider := self.providers.get(sso_provider_id)) is not None:
            provider.domain = ""
            provider.domain_verified = False
            provider.domain_verification_token = None
            provider.domain_verification_token_expires_at = None
        return len(domain_ids)

    def _sync_domains_for_provider(self, provider: FakeProvider) -> None:
        existing_domains = {
            domain.domain: domain for domain in self.domains.values() if domain.sso_provider_id == provider.id
        }
        active_domains = set(split_provider_domains(provider.domain))
        for domain_id, domain in list(self.domains.items()):
            if domain.sso_provider_id == provider.id and domain.domain not in active_domains:
                self.domains.pop(domain_id)
        for domain in active_domains:
            if domain in existing_domains:
                existing = existing_domains[domain]
                existing.verification_token = provider.domain_verification_token or existing.verification_token
                existing.verification_token_expires_at = provider.domain_verification_token_expires_at
                existing.verified_at = provider.updated_at if provider.domain_verified else None
                existing.updated_at = provider.updated_at
                continue
            domain_id = uuid4()
            self.domains[domain_id] = FakeDomain(
                id=domain_id,
                sso_provider_id=provider.id,
                domain=domain,
                verification_token=provider.domain_verification_token or "",
                verification_token_expires_at=provider.domain_verification_token_expires_at,
                verified_at=provider.updated_at if provider.domain_verified else None,
                created_at=provider.created_at,
                updated_at=provider.updated_at,
            )


class MemoryOrganizationAdapter:
    def __init__(self, organization: FakeOrganization, member: FakeMember) -> None:
        self.organization = organization
        self.member = member

    async def get_organization_by_id(self, _session: object, organization_id: UUID) -> FakeOrganization | None:
        if organization_id == self.organization.id:
            return self.organization
        return None

    async def get_member(self, _session: object, *, organization_id: UUID, individual_id: UUID) -> FakeMember | None:
        if organization_id == self.member.organization_id and individual_id == self.member.individual_id:
            return self.member
        return None


def build_client() -> tuple[SSOClient, MemorySSOAdapter, FakeOrganization, FakeIndividual]:
    admin_individual = FakeIndividual(
        id=uuid4(),
        email="owner@example.com",
        email_verified_at=datetime.now(UTC),
        name="Owner",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )
    organization = FakeOrganization(
        id=uuid4(),
        name="Acme",
        slug="acme",
        logo=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    member = FakeMember(
        id=uuid4(),
        organization_id=organization.id,
        individual_id=admin_individual.id,
        role="owner",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    sso_adapter = MemorySSOAdapter()
    organization_adapter = MemoryOrganizationAdapter(organization, member)
    settings = EnterpriseSSO(adapter=sso_adapter, providers_limit=2)
    client = SSOClient(
        client=SimpleNamespace(db=object()),
        base_url="https://app.example.com",
        settings=settings,
        organization_adapter=organization_adapter,
        current_individual=admin_individual,
    )
    return client, sso_adapter, organization, admin_individual


def test_default_scopes_include_offline_access() -> None:
    sso_client, _, _, _ = build_client()

    assert sso_client.settings.default_scopes == ["openid", "email", "profile", "offline_access"]


@pytest.mark.asyncio
async def test_register_oidc_provider_supports_user_owned_providers(monkeypatch) -> None:
    sso_client, sso_adapter, _, admin_individual = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
            discovery_endpoint="https://idp.example.com/.well-known/openid-configuration",
            claim_mapping=OIDCClaimMapping(),
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )

    provider = await sso_client.register_oidc_provider(
        provider_id="Acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["Example.com"],
    )

    assert provider.provider_id == "acme"
    assert provider.organization_id is None
    assert provider.created_by_individual_id == admin_individual.id
    assert provider.provider_type == "oidc"
    stored_domains = await sso_adapter.list_domains_for_provider(object(), sso_provider_id=provider.id)
    assert [domain.domain for domain in stored_domains] == ["example.com"]


@pytest.mark.asyncio
async def test_register_oidc_provider_requires_org_admin_for_org_provider(monkeypatch) -> None:
    sso_client, _, organization, _ = build_client()
    sso_client.organization_adapter.member.role = "member"
    monkeypatch.setattr("belgie_sso.client.discover_oidc_configuration", AsyncMock())

    with pytest.raises(HTTPException, match="organization admin access is required"):
        await sso_client.register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )


@pytest.mark.asyncio
async def test_create_domain_challenge_returns_provider_scoped_dns_record(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    challenge = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")

    assert challenge.record_name == "_belgie-sso-acme.example.com"
    assert challenge.record_value.startswith("_belgie-sso-acme=")


@pytest.mark.asyncio
async def test_verify_domain_uses_provider_scoped_dns_value(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    challenge = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    monkeypatch.setattr(
        "belgie_sso.client.lookup_txt_records",
        AsyncMock(return_value=[challenge.record_value]),
    )

    verified = await sso_client.verify_domain(provider_id=provider.provider_id, domain="example.com")

    assert verified.domain_verified is True
    assert verified.domain_verification_token is None


@pytest.mark.asyncio
async def test_verify_domain_surfaces_dns_resolution_failures(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    monkeypatch.setattr(
        "belgie_sso.client.lookup_txt_records",
        AsyncMock(side_effect=DNSTxtLookupError("failed to resolve DNS TXT records")),
    )

    with pytest.raises(HTTPException, match="failed to resolve DNS TXT records") as exc_info:
        await sso_client.verify_domain(provider_id=provider.provider_id, domain="example.com")

    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_list_provider_summaries_masks_client_id_and_derives_domain_verified(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id-1234",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id-1234",
        client_secret="client-secret",
        domains=["example.com"],
    )
    await sso_client.settings.adapter.update_domain(
        sso_client.client.db,
        domain_id=(
            await sso_client.settings.adapter.list_domains_for_provider(
                sso_client.client.db,
                sso_provider_id=provider.id,
            )
        )[0].id,
        verified_at=datetime.now(UTC),
    )

    summary = await sso_client.get_provider_summary(provider_id="acme")

    assert summary.client_id == "****1234"
    assert summary.domain_verified is True
    assert summary.verified_domains == ("example.com",)


@pytest.mark.asyncio
async def test_get_provider_detail_redacts_client_secret(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id-1234",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id-1234",
        client_secret="client-secret",
        domains=["example.com"],
    )

    detail = await sso_client.get_provider_detail(provider_id="acme")

    assert detail.config["client_id"] == "****1234"
    assert "client_secret" not in detail.config


@pytest.mark.asyncio
async def test_create_domain_challenge_reuses_active_token(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    first = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    second = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")

    assert second.verification_token == first.verification_token
    assert second.expires_at == first.expires_at


@pytest.mark.asyncio
async def test_create_domain_challenge_uses_custom_domain_txt_prefix(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    sso_client.settings.domain_txt_prefix = "corp-sso"
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    challenge = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")

    assert challenge.record_name == "_corp-sso-acme.example.com"
    assert challenge.record_value.startswith("_corp-sso-acme=")


@pytest.mark.asyncio
async def test_create_domain_challenge_rotates_expired_token(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    first = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    provider.domain_verification_token_expires_at = datetime.now(UTC)

    second = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")

    assert second.verification_token != first.verification_token
    assert second.expires_at is not None
    assert second.expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_create_domain_challenge_rejects_verified_domain(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    provider.domain_verified = True

    with pytest.raises(HTTPException) as exc_info:
        await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "domain is already verified"


@pytest.mark.asyncio
async def test_verify_domain_rejects_expired_challenge(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    provider.domain_verification_token_expires_at = datetime.now(UTC)

    with pytest.raises(HTTPException) as exc_info:
        await sso_client.verify_domain(provider_id=provider.provider_id, domain="example.com")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "pending domain verification challenge not found"


@pytest.mark.asyncio
async def test_verify_domain_rejects_verified_domain(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    provider.domain_verified = True

    with pytest.raises(HTTPException) as exc_info:
        await sso_client.verify_domain(provider_id=provider.provider_id, domain="example.com")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "domain is already verified"


@pytest.mark.asyncio
async def test_provider_limit_supports_callable(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    sso_client.settings.providers_limit = lambda _organization_id: 1
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )

    await sso_client.register_oidc_provider(
        provider_id="one",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(HTTPException, match="provider limit reached"):
        await sso_client.register_oidc_provider(
            provider_id="two",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )


@pytest.mark.asyncio
async def test_provider_limit_applies_per_owner(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )

    await sso_client.register_oidc_provider(
        provider_id="one",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )
    await sso_client.register_oidc_provider(
        provider_id="two",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(HTTPException, match="provider limit reached"):
        await sso_client.register_oidc_provider(
            provider_id="three",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )


@pytest.mark.asyncio
async def test_provider_limit_zero_disables_registration(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    sso_client.settings.providers_limit = 0
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )

    with pytest.raises(HTTPException, match="provider registration is disabled"):
        await sso_client.register_oidc_provider(
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )


@pytest.mark.asyncio
async def test_register_saml_provider_creates_saml_provider_snapshot() -> None:
    sso_client, _, _, _ = build_client()

    provider = await sso_client.register_saml_provider(
        provider_id="acme-saml",
        issuer="https://idp.example.com",
        entity_id="urn:acme:sp",
        sso_url="https://idp.example.com/sso",
        x509_certificate="certificate",
        domains=["example.com"],
    )

    assert provider.provider_type == "saml"
    assert provider.oidc_config is None
    assert provider.saml_config is not None
    assert deserialize_saml_config(provider.saml_config).allow_idp_initiated is True


@pytest.mark.asyncio
async def test_get_saml_provider_detail_redacts_secret_material() -> None:
    sso_client, _, _, _ = build_client()
    await sso_client.register_saml_provider(
        provider_id="acme-saml",
        issuer="https://idp.example.com",
        entity_id="urn:acme:sp",
        sso_url="https://idp.example.com/sso",
        x509_certificate="-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----",
        private_key="test-private-key",
        signing_certificate="-----BEGIN CERTIFICATE-----\nxyz\n-----END CERTIFICATE-----",
    )

    detail = await sso_client.get_provider_detail(provider_id="acme-saml")

    assert detail.config["private_key_present"] is True
    assert detail.config["signing_certificate_present"] is True
    assert detail.config["x509_certificate_present"] is True
    assert "private_key" not in detail.config
    assert "signing_certificate" not in detail.config


@pytest.mark.asyncio
async def test_get_saml_provider_detail_only_exposes_metadata_presence_flags() -> None:
    sso_client, _, _, _ = build_client()
    await sso_client.register_saml_provider(
        provider_id="acme-saml",
        issuer="https://idp.example.com",
        entity_id="urn:acme:sp",
        sso_url="https://idp.example.com/sso",
        x509_certificate="-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----",
        idp_metadata_xml="<EntityDescriptor/>",
        sp_metadata_xml="<EntityDescriptor entityID='urn:custom:sp'/>",
    )

    detail = await sso_client.get_provider_detail(provider_id="acme-saml")

    assert detail.config["idp_metadata_xml_present"] is True
    assert detail.config["sp_metadata_xml_present"] is True
    assert "idp_metadata_xml" not in detail.config
    assert "sp_metadata_xml" not in detail.config


@pytest.mark.asyncio
async def test_register_oidc_provider_rejects_duplicate_provider_id(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(HTTPException, match="provider_id already exists"):
        await sso_client.register_oidc_provider(
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="other-client-id",
            client_secret="other-client-secret",
        )


@pytest.mark.asyncio
async def test_register_oidc_provider_rejects_unsupported_token_endpoint_auth_method_when_skip_discovery() -> None:
    sso_client, _, _, _ = build_client()

    with pytest.raises(
        HTTPException,
        match="token endpoint auth method 'private_key_jwt' is not supported",
    ) as exc_info:
        await sso_client.register_oidc_provider(
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
            jwks_uri="https://idp.example.com/jwks",
            token_endpoint_auth_method="private_key_jwt",
            skip_discovery=True,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_oidc_provider_preserves_existing_fields_when_partially_updating(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            side_effect=[
                OIDCDiscoveryResult(
                    issuer="https://idp.example.com",
                    config=OIDCProviderConfig(
                        issuer="https://idp.example.com",
                        client_id="client-id",
                        client_secret="client-secret",
                        authorization_endpoint="https://idp.example.com/authorize",
                        token_endpoint="https://idp.example.com/token",
                        userinfo_endpoint="https://idp.example.com/userinfo",
                    ),
                ),
                OIDCDiscoveryResult(
                    issuer="https://idp.example.com/updated",
                    config=OIDCProviderConfig(
                        issuer="https://idp.example.com/updated",
                        client_id="client-id",
                        client_secret="client-secret",
                        authorization_endpoint="https://idp.example.com/updated/authorize",
                        token_endpoint="https://idp.example.com/updated/token",
                        userinfo_endpoint="https://idp.example.com/updated/userinfo",
                        jwks_uri="https://idp.example.com/updated/jwks",
                    ),
                ),
            ],
        ),
    )
    await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    updated = await sso_client.update_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com/updated",
        domains=["example.com", "dept.example.com"],
    )

    updated_config = sso_client._provider_oidc_config(updated)
    assert updated.issuer == "https://idp.example.com/updated"
    assert updated_config.client_id == "client-id"
    assert updated_config.userinfo_endpoint == "https://idp.example.com/updated/userinfo"
    assert {
        domain.domain
        for domain in await sso_client.settings.adapter.list_domains_for_provider(
            sso_client.client.db,
            sso_provider_id=updated.id,
        )
    } == {"example.com", "dept.example.com"}


@pytest.mark.asyncio
async def test_update_oidc_provider_rejects_empty_patch(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(HTTPException, match="at least one update field must be provided") as exc_info:
        await sso_client.update_oidc_provider(provider_id="acme")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_oidc_provider_rejects_unsupported_token_endpoint_auth_method_when_skip_discovery() -> None:
    sso_client, _, _, _ = build_client()
    await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        userinfo_endpoint="https://idp.example.com/userinfo",
        jwks_uri="https://idp.example.com/jwks",
        skip_discovery=True,
    )

    with pytest.raises(
        HTTPException,
        match="token endpoint auth method 'private_key_jwt' is not supported",
    ) as exc_info:
        await sso_client.update_oidc_provider(
            provider_id="acme",
            token_endpoint_auth_method="private_key_jwt",
            skip_discovery=True,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_saml_provider_preserves_existing_fields_when_partially_updating() -> None:
    sso_client, _, _, _ = build_client()
    await sso_client.register_saml_provider(
        provider_id="acme-saml",
        issuer="https://idp.example.com",
        entity_id="urn:acme:sp",
        sso_url="https://idp.example.com/sso",
        x509_certificate="certificate",
        signing_certificate="signing-certificate",
        domains=["example.com"],
    )

    updated = await sso_client.update_saml_provider(
        provider_id="acme-saml",
        sso_url="https://idp.example.com/updated/sso",
    )

    updated_config = deserialize_saml_config(updated.saml_config or {})
    assert updated_config.entity_id == "urn:acme:sp"
    assert updated_config.sso_url == "https://idp.example.com/updated/sso"
    assert updated_config.signing_certificate == "signing-certificate"


@pytest.mark.asyncio
async def test_update_saml_provider_rejects_empty_patch() -> None:
    sso_client, _, _, _ = build_client()
    await sso_client.register_saml_provider(
        provider_id="acme-saml",
        issuer="https://idp.example.com",
        entity_id="urn:acme:sp",
        sso_url="https://idp.example.com/sso",
        x509_certificate="certificate",
        sign_authn_request=False,
    )

    with pytest.raises(HTTPException, match="at least one update field must be provided") as exc_info:
        await sso_client.update_saml_provider(provider_id="acme-saml")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_provider_removes_provider_domains(monkeypatch) -> None:
    sso_client, adapter, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    deleted = await sso_client.delete_provider(provider_id=provider.provider_id)

    assert deleted is True
    assert await adapter.get_provider_by_provider_id(sso_client.client.db, provider_id="acme") is None
    assert await adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id) == []


@pytest.mark.asyncio
async def test_register_saml_provider_rejects_invalid_binding() -> None:
    sso_client, _, _, _ = build_client()

    with pytest.raises(HTTPException, match="binding must be one of: post, redirect") as exc_info:
        await sso_client.register_saml_provider(
            provider_id="acme-saml",
            issuer="https://idp.example.com",
            entity_id="urn:acme:sp",
            sso_url="https://idp.example.com/sso",
            x509_certificate="certificate",
            binding="artifact",
            sign_authn_request=False,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_register_saml_provider_rejects_blank_sso_url() -> None:
    sso_client, _, _, _ = build_client()

    with pytest.raises(HTTPException, match="sso_url must be an absolute http\\(s\\) URL") as exc_info:
        await sso_client.register_saml_provider(
            provider_id="acme-saml",
            issuer="https://idp.example.com",
            entity_id="urn:acme:sp",
            sso_url=" ",
            x509_certificate="certificate",
            sign_authn_request=False,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_register_saml_provider_rejects_deprecated_signature_algorithm_when_configured() -> None:
    sso_client, _, _, _ = build_client()
    sso_client.settings.saml = replace(sso_client.settings.saml, on_deprecated="reject")

    with pytest.raises(
        HTTPException,
        match="SAML config uses deprecated signature algorithm: rsa-sha1",
    ) as exc_info:
        await sso_client.register_saml_provider(
            provider_id="acme-saml",
            issuer="https://idp.example.com",
            entity_id="urn:acme:sp",
            sso_url="https://idp.example.com/sso",
            x509_certificate="certificate",
            signature_algorithm="rsa-sha1",
            sign_authn_request=False,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_list_provider_summaries_only_returns_current_individual_providers(monkeypatch) -> None:
    sso_client, adapter, organization, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    await sso_client.register_oidc_provider(
        provider_id="mine",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )
    await adapter.create_provider(
        sso_client.client.db,
        organization_id=None,
        created_by_individual_id=uuid4(),
        provider_type="oidc",
        provider_id="theirs",
        issuer="https://idp.example.com",
        oidc_config=None,
        saml_config=None,
    )
    await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="org-owned",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    summaries = await sso_client.list_provider_summaries()

    assert [summary.provider_id for summary in summaries] == ["mine"]


@pytest.mark.asyncio
async def test_list_providers_for_organization_requires_org_admin(monkeypatch) -> None:
    sso_client, _, organization, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="org-acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )
    sso_client.organization_adapter.member.role = "member"

    with pytest.raises(HTTPException, match="organization admin access is required"):
        await sso_client.list_provider_summaries(organization_id=organization.id)


@pytest.mark.asyncio
async def test_update_oidc_provider_rejects_domain_registered_to_another_provider(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    await sso_client.register_oidc_provider(
        provider_id="one",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    provider_two = await sso_client.register_oidc_provider(
        provider_id="two",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(HTTPException, match=r"domain 'example\.com' is already registered"):
        await sso_client.update_oidc_provider(provider_id=provider_two.provider_id, domain="example.com")


@pytest.mark.asyncio
async def test_create_domain_challenge_rejects_dns_labels_longer_than_limit(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    long_provider_id = "a" * 60
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                ),
            ),
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id=long_provider_id,
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    with pytest.raises(HTTPException, match="domain verification record label exceeds DNS limits"):
        await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")


@pytest.mark.asyncio
async def test_updating_domains_drops_provider_level_verified_status_when_verified_domain_is_removed(
    monkeypatch,
) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            side_effect=[
                OIDCDiscoveryResult(
                    issuer="https://idp.example.com",
                    config=OIDCProviderConfig(
                        issuer="https://idp.example.com",
                        client_id="client-id",
                        client_secret="client-secret",
                        authorization_endpoint="https://idp.example.com/authorize",
                        token_endpoint="https://idp.example.com/token",
                        userinfo_endpoint="https://idp.example.com/userinfo",
                    ),
                ),
                OIDCDiscoveryResult(
                    issuer="https://idp.example.com",
                    config=OIDCProviderConfig(
                        issuer="https://idp.example.com",
                        client_id="client-id",
                        client_secret="client-secret",
                        authorization_endpoint="https://idp.example.com/authorize",
                        token_endpoint="https://idp.example.com/token",
                        userinfo_endpoint="https://idp.example.com/userinfo",
                    ),
                ),
            ],
        ),
    )
    provider = await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com", "dept.example.com"],
    )
    example_domain = next(
        domain
        for domain in await sso_client.settings.adapter.list_domains_for_provider(
            sso_client.client.db,
            sso_provider_id=provider.id,
        )
        if domain.domain == "example.com"
    )
    await sso_client.settings.adapter.update_domain(
        sso_client.client.db,
        domain_id=example_domain.id,
        verified_at=datetime.now(UTC),
    )

    await sso_client.update_oidc_provider(
        provider_id="acme",
        domains=["dept.example.com"],
    )
    summary = await sso_client.get_provider_summary(provider_id="acme")

    assert summary.domain_verified is False
    assert summary.verified_domains == ()


@pytest.mark.asyncio
async def test_register_oidc_provider_maps_discovery_timeout_to_http_exception(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            side_effect=DiscoveryError(
                "discovery_timeout",
                "Discovery request timed out",
            ),
        ),
    )

    with pytest.raises(HTTPException, match="OIDC discovery timed out"):
        await sso_client.register_oidc_provider(
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )


@pytest.mark.asyncio
async def test_update_oidc_provider_maps_discovery_invalid_json_to_http_exception(monkeypatch) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            side_effect=[
                OIDCDiscoveryResult(
                    issuer="https://idp.example.com",
                    config=OIDCProviderConfig(
                        issuer="https://idp.example.com",
                        client_id="client-id",
                        client_secret="client-secret",
                        authorization_endpoint="https://idp.example.com/authorize",
                        token_endpoint="https://idp.example.com/token",
                        userinfo_endpoint="https://idp.example.com/userinfo",
                    ),
                ),
                DiscoveryError(
                    "discovery_invalid_json",
                    "Discovery endpoint returned invalid JSON",
                ),
            ],
        ),
    )
    await sso_client.register_oidc_provider(
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(HTTPException, match="OIDC discovery returned invalid data"):
        await sso_client.update_oidc_provider(
            provider_id="acme",
            issuer="https://idp.example.com/updated",
        )
