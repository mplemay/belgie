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
from belgie_sso.utils import serialize_oidc_config
from fastapi import HTTPException


@dataclass
class FakeUser:
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
    user_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeProvider:
    id: UUID
    organization_id: UUID
    provider_id: str
    issuer: str
    oidc_config: dict[str, str | list[str] | dict[str, str]]
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeDomain:
    id: UUID
    sso_provider_id: UUID
    domain: str
    verification_token: str
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
        organization_id: UUID,
        provider_id: str,
        issuer: str,
        oidc_config: dict[str, str | list[str] | dict[str, str]],
    ) -> FakeProvider:
        now = datetime.now(UTC)
        provider = FakeProvider(
            id=uuid4(),
            organization_id=organization_id,
            provider_id=provider_id,
            issuer=issuer,
            oidc_config=oidc_config,
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

    async def update_provider(
        self,
        _session: object,
        *,
        sso_provider_id: UUID,
        issuer: str | None = None,
        oidc_config: dict[str, str | list[str] | dict[str, str]] | None = None,
    ) -> FakeProvider | None:
        provider = self.providers.get(sso_provider_id)
        if provider is None:
            return None
        if issuer is not None:
            provider.issuer = issuer
        if oidc_config is not None:
            provider.oidc_config = oidc_config
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
    ) -> FakeDomain:
        now = datetime.now(UTC)
        sso_domain = FakeDomain(
            id=uuid4(),
            sso_provider_id=sso_provider_id,
            domain=domain,
            verification_token=verification_token,
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

    async def list_domains_for_provider(self, _session: object, *, sso_provider_id: UUID) -> list[FakeDomain]:
        return [item for item in self.domains.values() if item.sso_provider_id == sso_provider_id]

    async def update_domain(
        self,
        _session: object,
        *,
        domain_id: UUID,
        verification_token: str | None = None,
        verified_at: datetime | None = None,
    ) -> FakeDomain | None:
        sso_domain = self.domains.get(domain_id)
        if sso_domain is None:
            return None
        if verification_token is not None:
            sso_domain.verification_token = verification_token
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
        self.created_members: list[FakeMember] = []

    async def get_organization_by_id(self, _session: object, organization_id: UUID) -> FakeOrganization | None:
        if organization_id == self.organization.id:
            return self.organization
        return None

    async def get_member(self, _session: object, *, organization_id: UUID, user_id: UUID) -> FakeMember | None:
        if organization_id == self.member.organization_id and user_id == self.member.user_id:
            return self.member
        return next(
            (
                member
                for member in self.created_members
                if member.organization_id == organization_id and member.user_id == user_id
            ),
            None,
        )

    async def create_member(self, _session: object, *, organization_id: UUID, user_id: UUID, role: str) -> FakeMember:
        member = FakeMember(
            id=uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.created_members.append(member)
        return member


def build_client() -> tuple[SSOClient, MemorySSOAdapter, MemoryOrganizationAdapter, FakeOrganization, FakeUser]:
    admin_user = FakeUser(
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
        user_id=admin_user.id,
        role="owner",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    sso_adapter = MemorySSOAdapter()
    organization_adapter = MemoryOrganizationAdapter(organization, member)
    settings = EnterpriseSSO(adapter=sso_adapter)
    client = SSOClient(
        client=SimpleNamespace(db=object()),
        settings=settings,
        organization_adapter=organization_adapter,
        current_user=admin_user,
    )
    return client, sso_adapter, organization_adapter, organization, admin_user


@pytest.mark.asyncio
async def test_register_oidc_provider_discovers_and_persists_domains(monkeypatch) -> None:
    sso_client, sso_adapter, _, organization, _ = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
            jwks_uri="https://idp.example.com/jwks",
            claim_mapping=OIDCClaimMapping(),
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )

    provider = await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="Acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["Example.com", "dept.example.com"],
    )

    assert provider.provider_id == "acme"
    stored_provider = await sso_adapter.get_provider_by_provider_id(object(), provider_id="acme")
    assert stored_provider is not None
    assert stored_provider.oidc_config == serialize_oidc_config(discovery.config)
    stored_domains = await sso_adapter.list_domains_for_provider(object(), sso_provider_id=provider.id)
    assert [domain.domain for domain in stored_domains] == ["example.com", "dept.example.com"]


@pytest.mark.asyncio
async def test_register_oidc_provider_rejects_malformed_provider_id() -> None:
    sso_client, _, _, organization, _ = build_client()
    with pytest.raises(HTTPException) as exc_info:
        await sso_client.register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme!",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            domains=["example.com"],
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_provider_rejects_malformed_provider_id() -> None:
    sso_client, _, _, _, _ = build_client()
    with pytest.raises(HTTPException) as exc_info:
        await sso_client.get_provider(provider_id="acme!")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_register_oidc_provider_requires_org_admin(monkeypatch) -> None:
    sso_client, _, organization_adapter, organization, _ = build_client()
    organization_adapter.member.role = "member"
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(),
    )

    with pytest.raises(HTTPException, match="organization admin access is required"):
        await sso_client.register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            domains=["example.com"],
        )


@pytest.mark.asyncio
async def test_verify_domain_marks_domain_as_verified(monkeypatch) -> None:
    sso_client, _, _, organization, _ = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )
    provider = await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    domain = (
        await sso_client.settings.adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id)
    )[0]
    monkeypatch.setattr(
        "belgie_sso.client.lookup_txt_records",
        AsyncMock(return_value=[domain.verification_token]),
    )

    verified_domain = await sso_client.verify_domain(provider_id="acme", domain="example.com")

    assert verified_domain.verified_at is not None


@pytest.mark.asyncio
async def test_create_domain_challenge_rotates_token_and_clears_verification(monkeypatch) -> None:
    sso_client, _, _, organization, _ = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )
    provider = await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    existing_domain = (
        await sso_client.settings.adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id)
    )[0]
    existing_token = existing_domain.verification_token
    await sso_client.settings.adapter.update_domain(
        sso_client.client.db,
        domain_id=existing_domain.id,
        verified_at=datetime.now(UTC),
    )

    challenged_domain = await sso_client.create_domain_challenge(provider_id="acme", domain="example.com")

    assert challenged_domain.domain == "example.com"
    assert challenged_domain.verification_token != existing_token
    assert challenged_domain.verified_at is None


@pytest.mark.asyncio
async def test_update_oidc_provider_replaces_domains(monkeypatch) -> None:
    sso_client, _, _, organization, _ = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )
    provider = await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    updated = await sso_client.update_oidc_provider(
        provider_id=provider.provider_id,
        domains=["dept.example.com"],
        client_id="new-client-id",
        client_secret="new-client-secret",
    )

    stored_domains = await sso_client.settings.adapter.list_domains_for_provider(
        sso_client.client.db,
        sso_provider_id=provider.id,
    )
    assert updated.id == provider.id
    assert [domain.domain for domain in stored_domains] == ["dept.example.com"]


@pytest.mark.asyncio
async def test_update_oidc_provider_preserves_verified_domains_when_domain_list_unchanged(monkeypatch) -> None:
    sso_client, _, _, organization, _ = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )
    provider = await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )
    existing_domain = (
        await sso_client.settings.adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id)
    )[0]
    verified_at = datetime.now(UTC)
    token_before = existing_domain.verification_token
    await sso_client.settings.adapter.update_domain(
        sso_client.client.db,
        domain_id=existing_domain.id,
        verified_at=verified_at,
    )

    updated_discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="new-client-id",
            client_secret="new-client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=updated_discovery),
    )
    await sso_client.update_oidc_provider(
        provider_id=provider.provider_id,
        domains=["example.com"],
        client_id="new-client-id",
        client_secret="new-client-secret",
    )

    stored = (
        await sso_client.settings.adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id)
    )[0]
    assert stored.domain == "example.com"
    assert stored.verification_token == token_before
    assert stored.verified_at == verified_at


@pytest.mark.asyncio
async def test_register_oidc_provider_rejects_registered_domain(monkeypatch) -> None:
    sso_client, _, _, organization, _ = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )
    await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    with pytest.raises(HTTPException, match="already registered"):
        await sso_client.register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme-two",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            domains=["example.com"],
        )


@pytest.mark.asyncio
async def test_delete_provider_removes_provider_and_domains(monkeypatch) -> None:
    sso_client, _, _, organization, _ = build_client()
    discovery = OIDCDiscoveryResult(
        issuer="https://idp.example.com",
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
        ),
    )
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(return_value=discovery),
    )
    provider = await sso_client.register_oidc_provider(
        organization_id=organization.id,
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        domains=["example.com"],
    )

    deleted = await sso_client.delete_provider(provider_id=provider.provider_id)

    assert deleted is True
    assert (
        await sso_client.settings.adapter.get_provider_by_provider_id(sso_client.client.db, provider_id="acme") is None
    )
    assert (
        await sso_client.settings.adapter.list_domains_for_provider(sso_client.client.db, sso_provider_id=provider.id)
    ) == []
