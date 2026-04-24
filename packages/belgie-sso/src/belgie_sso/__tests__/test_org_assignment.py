from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from belgie_sso.__tests__.support import (
    MemoryOrganizationAdapter,
    MemorySSOAdapter,
    build_domain,
    build_individual,
    build_organization,
    build_provider,
)
from belgie_sso.org_assignment import (
    assign_individual_by_domain,
    assign_individual_by_verified_domain,
    provider_matches_domain,
    provider_matches_verified_domain,
)


def _provider(*, organization_id=None):
    return build_provider(
        organization_id=organization_id,
        domain="",
        oidc_config={},
    )


@pytest.mark.asyncio
async def test_provider_matches_verified_domain_uses_longest_verified_suffix() -> None:
    provider = _provider(organization_id=uuid4())
    adapter = MemorySSOAdapter(
        [provider],
        [
            build_domain(
                sso_provider_id=provider.id,
                verified_at=datetime.now(UTC),
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
    adapter = MemorySSOAdapter(
        [provider],
        [
            build_domain(
                sso_provider_id=provider.id,
                verified_at=datetime.now(UTC),
            ),
        ],
    )
    organization = build_organization()
    organization.id = organization_id
    organization_adapter = MemoryOrganizationAdapter(organization)
    individual = build_individual(email="person@dept.example.com", name="Person")

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
    assert organization_adapter.created_members == [(organization_id, individual.id, "member")]


@pytest.mark.asyncio
async def test_assign_individual_by_verified_domain_skips_user_owned_provider() -> None:
    provider = _provider(organization_id=None)
    adapter = MemorySSOAdapter(
        [provider],
        [
            build_domain(
                sso_provider_id=provider.id,
                verified_at=datetime.now(UTC),
            ),
        ],
    )
    individual = build_individual(email="person@example.com", name="Person")

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
    adapter = MemorySSOAdapter(
        [provider],
        [
            build_domain(
                sso_provider_id=provider.id,
                verified_at=None,
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
    adapter = MemorySSOAdapter(
        [provider],
        [
            build_domain(
                sso_provider_id=provider.id,
                verified_at=None,
            ),
        ],
    )
    organization = build_organization()
    organization.id = organization_id
    organization_adapter = MemoryOrganizationAdapter(organization)
    individual = build_individual(email="person@dept.example.com", name="Person")

    assert await assign_individual_by_domain(
        db=object(),
        adapter=adapter,
        organization_adapter=organization_adapter,
        individual=individual,
        email=individual.email,
        verified_only=False,
    )
