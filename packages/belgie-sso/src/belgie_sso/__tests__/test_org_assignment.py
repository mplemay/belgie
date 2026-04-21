from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from belgie_sso.org_assignment import assign_individual_by_verified_domain, provider_matches_verified_domain
from belgie_sso.settings import OrganizationProvisioningOptions


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


class FakeSSOAdapter:
    def __init__(self, provider: FakeProvider, domains: list[FakeDomain]) -> None:
        self.provider = provider
        self.domains = domains

    async def list_domains_for_provider(self, _db: object, *, sso_provider_id: UUID) -> list[FakeDomain]:
        if sso_provider_id == self.provider.id:
            return list(self.domains)
        return []

    async def get_verified_domain(self, _db: object, *, domain: str) -> FakeDomain | None:
        return next((item for item in self.domains if item.domain == domain and item.verified_at is not None), None)

    async def get_best_verified_domain(self, _db: object, *, domain: str) -> FakeDomain | None:
        matches = [
            item
            for item in self.domains
            if item.verified_at is not None and (domain == item.domain or domain.endswith(f".{item.domain}"))
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: len(item.domain), reverse=True)
        return matches[0]

    async def get_provider_by_id(self, _db: object, *, sso_provider_id: UUID) -> FakeProvider | None:
        if sso_provider_id == self.provider.id:
            return self.provider
        return None


class FakeOrganizationAdapter:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.members: list[tuple[UUID, UUID, str]] = []

    async def get_organization_by_id(self, _db: object, organization_id: UUID) -> object | None:
        if organization_id == self.organization_id:
            return object()
        return None

    async def get_member(self, _db: object, *, organization_id: UUID, individual_id: UUID) -> object | None:
        return next(
            (
                object()
                for existing_organization_id, existing_user_id, _role in self.members
                if existing_organization_id == organization_id and existing_user_id == individual_id
            ),
            None,
        )

    async def create_member(self, _db: object, *, organization_id: UUID, individual_id: UUID, role: str) -> object:
        self.members.append((organization_id, individual_id, role))
        return object()


@pytest.mark.asyncio
async def test_provider_matches_verified_domain_accepts_verified_parent_domains() -> None:
    provider = FakeProvider(
        id=uuid4(),
        organization_id=uuid4(),
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    adapter = FakeSSOAdapter(
        provider,
        [
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="example.com",
                verification_token="token",
                verified_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ],
    )

    assert await provider_matches_verified_domain(
        db=object(),
        adapter=adapter,
        provider=provider,
        email="a@example.com",
    )
    assert await provider_matches_verified_domain(
        db=object(),
        adapter=adapter,
        provider=provider,
        email="a@dept.example.com",
    )


@pytest.mark.asyncio
async def test_assign_individual_by_verified_domain_is_idempotent() -> None:
    organization_id = uuid4()
    provider = FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    domain = FakeDomain(
        id=uuid4(),
        sso_provider_id=provider.id,
        domain="example.com",
        verification_token="token",
        verified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    adapter = FakeSSOAdapter(provider, [domain])
    organization_adapter = FakeOrganizationAdapter(organization_id)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@example.com",
        email_verified_at=datetime.now(UTC),
        name="Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )

    assert await assign_individual_by_verified_domain(
        db=object(),
        adapter=adapter,
        organization_adapter=organization_adapter,
        individual=individual,
        email=individual.email,
    )
    assert not await assign_individual_by_verified_domain(
        db=object(),
        adapter=adapter,
        organization_adapter=organization_adapter,
        individual=individual,
        email=individual.email,
    )
    assert organization_adapter.members == [(organization_id, individual.id, "member")]


@pytest.mark.asyncio
async def test_assign_individual_by_verified_domain_skips_deleted_provider() -> None:
    organization_id = uuid4()
    provider = FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    domain = FakeDomain(
        id=uuid4(),
        sso_provider_id=provider.id,
        domain="example.com",
        verification_token="token",
        verified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    adapter = FakeSSOAdapter(provider, [domain])
    organization_adapter = FakeOrganizationAdapter(organization_id)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@example.com",
        email_verified_at=datetime.now(UTC),
        name="Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )

    adapter.provider = FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        provider_id="other",
        issuer="https://idp.example.com",
        oidc_config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert not await assign_individual_by_verified_domain(
        db=object(),
        adapter=adapter,
        organization_adapter=organization_adapter,
        individual=individual,
        email=individual.email,
    )
    assert organization_adapter.members == []


@pytest.mark.asyncio
async def test_assign_individual_by_verified_domain_prefers_longest_matching_domain() -> None:
    organization_id = uuid4()
    provider = FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    adapter = FakeSSOAdapter(
        provider,
        [
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="example.com",
                verification_token="token-1",
                verified_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="dept.example.com",
                verification_token="token-2",
                verified_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ],
    )

    best = await adapter.get_best_verified_domain(object(), domain="a.team.dept.example.com")

    assert best is not None
    assert best.domain == "dept.example.com"


@pytest.mark.asyncio
async def test_assign_individual_by_verified_domain_uses_configured_role() -> None:
    organization_id = uuid4()
    provider = FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    domain = FakeDomain(
        id=uuid4(),
        sso_provider_id=provider.id,
        domain="example.com",
        verification_token="token",
        verified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    adapter = FakeSSOAdapter(provider, [domain])
    organization_adapter = FakeOrganizationAdapter(organization_id)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@example.com",
        email_verified_at=datetime.now(UTC),
        name="Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )

    assigned = await assign_individual_by_verified_domain(
        db=object(),
        adapter=adapter,
        organization_adapter=organization_adapter,
        individual=individual,
        email=individual.email,
        provisioning_options=OrganizationProvisioningOptions(default_role="admin"),
    )

    assert assigned is True
    assert organization_adapter.members == [(organization_id, individual.id, "admin")]
