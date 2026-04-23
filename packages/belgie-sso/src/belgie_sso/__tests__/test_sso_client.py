from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig
from belgie_sso.client import SSOClient
from belgie_sso.discovery import OIDCDiscoveryResult
from belgie_sso.settings import EnterpriseSSO
from belgie_sso.utils import deserialize_saml_config
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
            oidc_config=oidc_config,
            saml_config=saml_config,
            created_at=now,
            updated_at=now,
        )
        self.providers[provider.id] = provider
        return provider

    async def get_provider_by_id(self, _session: object, *, sso_provider_id: UUID) -> FakeProvider | None:
        return self.providers.get(sso_provider_id)

    async def get_provider_by_provider_id(self, _session: object, *, provider_id: str) -> FakeProvider | None:
        return next((provider for provider in self.providers.values() if provider.provider_id == provider_id), None)

    async def list_providers_for_organization(self, _session: object, *, organization_id: UUID) -> list[FakeProvider]:
        return [provider for provider in self.providers.values() if provider.organization_id == organization_id]

    async def list_providers_for_individual(self, _session: object, *, individual_id: UUID) -> list[FakeProvider]:
        return [provider for provider in self.providers.values() if provider.created_by_individual_id == individual_id]

    async def update_provider(
        self,
        _session: object,
        *,
        sso_provider_id: UUID,
        organization_id: UUID | None = None,
        created_by_individual_id: UUID | None = None,
        provider_type: str | None = None,
        issuer: str | None = None,
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
        if oidc_config is not None:
            provider.oidc_config = oidc_config
        if saml_config is not None:
            provider.saml_config = saml_config
        provider.updated_at = datetime.now(UTC)
        return provider

    async def delete_provider(self, _session: object, *, sso_provider_id: UUID) -> bool:
        provider = self.providers.pop(sso_provider_id, None)
        if provider is None:
            return False
        for domain_id in [domain.id for domain in self.domains.values() if domain.sso_provider_id == sso_provider_id]:
            self.domains.pop(domain_id)
        return True

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
        return sso_domain

    async def delete_domain(self, _session: object, *, domain_id: UUID) -> bool:
        if domain_id not in self.domains:
            return False
        self.domains.pop(domain_id)
        return True

    async def delete_domains_for_provider(self, _session: object, *, sso_provider_id: UUID) -> int:
        domain_ids = [item.id for item in self.domains.values() if item.sso_provider_id == sso_provider_id]
        for domain_id in domain_ids:
            self.domains.pop(domain_id)
        return len(domain_ids)


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
        settings=settings,
        organization_adapter=organization_adapter,
        current_individual=admin_individual,
    )
    return client, sso_adapter, organization, admin_individual


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

    assert verified.verified_at is not None


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
async def test_create_domain_challenge_rotates_expired_token(monkeypatch) -> None:
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
    first = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    domain = (await adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id))[0]
    domain.verification_token_expires_at = datetime.now(UTC)

    second = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")

    assert second.verification_token != first.verification_token
    assert second.expires_at is not None
    assert second.expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_verify_domain_rejects_expired_challenge(monkeypatch) -> None:
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
    await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    domain = (await adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id))[0]
    domain.verification_token_expires_at = datetime.now(UTC)

    with pytest.raises(HTTPException, match="verification token has expired"):
        await sso_client.verify_domain(provider_id=provider.provider_id, domain="example.com")


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
