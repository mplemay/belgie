from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from belgie_sso.org_assignment import (
    assign_individual_by_domain,
    assign_individual_by_verified_domain,
    provider_matches_domain,
    provider_matches_verified_domain,
)


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


class FakeSSOAdapter:
    def __init__(self, providers: list[FakeProvider], domains: list[FakeDomain]) -> None:
        self.providers = {provider.id: provider for provider in providers}
        self.domains = list(domains)

    async def list_verified_domains_matching(self, _db: object, *, domain: str) -> list[FakeDomain]:
        return [
            item
            for item in self.domains
            if item.verified_at is not None and (item.domain == domain or domain.endswith(f".{item.domain}"))
        ]

    async def list_domains_matching(self, _db: object, *, domain: str) -> list[FakeDomain]:
        return [item for item in self.domains if item.domain == domain or domain.endswith(f".{item.domain}")]

    async def get_provider_by_id(self, _db: object, *, sso_provider_id: UUID) -> FakeProvider | None:
        return self.providers.get(sso_provider_id)


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
                for existing_organization_id, existing_individual_id, _role in self.members
                if existing_organization_id == organization_id and existing_individual_id == individual_id
            ),
            None,
        )

    async def create_member(self, _db: object, *, organization_id: UUID, individual_id: UUID, role: str) -> object:
        self.members.append((organization_id, individual_id, role))
        return object()


def _provider(*, organization_id: UUID | None = None) -> FakeProvider:
    return FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        created_by_individual_id=None,
        provider_type="oidc",
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={},
        saml_config=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_provider_matches_verified_domain_uses_longest_verified_suffix() -> None:
    provider = _provider(organization_id=uuid4())
    adapter = FakeSSOAdapter(
        [provider],
        [
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="example.com",
                verification_token="token",
                verification_token_expires_at=None,
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
        email="a@dept.example.com",
    )


@pytest.mark.asyncio
async def test_assign_individual_by_verified_domain_is_idempotent_for_suffix_matches() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    adapter = FakeSSOAdapter(
        [provider],
        [
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="example.com",
                verification_token="token",
                verification_token_expires_at=None,
                verified_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ],
    )
    organization_adapter = FakeOrganizationAdapter(organization_id)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@dept.example.com",
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
async def test_assign_individual_by_verified_domain_skips_user_owned_provider() -> None:
    provider = _provider(organization_id=None)
    adapter = FakeSSOAdapter(
        [provider],
        [
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="example.com",
                verification_token="token",
                verification_token_expires_at=None,
                verified_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ],
    )
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

    assert not await assign_individual_by_verified_domain(
        db=object(),
        adapter=adapter,
        organization_adapter=None,
        individual=individual,
        email=individual.email,
    )


@pytest.mark.asyncio
async def test_provider_matches_domain_allows_unverified_match_when_verification_disabled() -> None:
    provider = _provider(organization_id=uuid4())
    adapter = FakeSSOAdapter(
        [provider],
        [
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="example.com",
                verification_token="token",
                verification_token_expires_at=None,
                verified_at=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ],
    )

    assert await provider_matches_domain(
        db=object(),
        adapter=adapter,
        provider=provider,
        email="a@dept.example.com",
        verified_only=False,
    )


@pytest.mark.asyncio
async def test_assign_individual_by_domain_uses_unverified_suffix_when_verification_disabled() -> None:
    organization_id = uuid4()
    provider = _provider(organization_id=organization_id)
    adapter = FakeSSOAdapter(
        [provider],
        [
            FakeDomain(
                id=uuid4(),
                sso_provider_id=provider.id,
                domain="example.com",
                verification_token="token",
                verification_token_expires_at=None,
                verified_at=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ],
    )
    organization_adapter = FakeOrganizationAdapter(organization_id)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@dept.example.com",
        email_verified_at=datetime.now(UTC),
        name="Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )

    assert await assign_individual_by_domain(
        db=object(),
        adapter=adapter,
        organization_adapter=organization_adapter,
        individual=individual,
        email=individual.email,
        verified_only=False,
    )
