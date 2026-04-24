from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig
from fastapi import HTTPException

from belgie_sso.__tests__.support import build_client, build_individual, build_member
from belgie_sso.discovery import DiscoveryError, OIDCDiscoveryResult
from belgie_sso.dns import DNSTxtLookupError
from belgie_sso.utils import deserialize_saml_config


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
async def test_register_oidc_provider_allows_org_member_for_org_provider(monkeypatch) -> None:
    sso_client, _, organization, _ = build_client()
    sso_client.organization_adapter.member.role = "member"
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
        organization_id=organization.id,
        provider_id="acme",
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    assert provider.organization_id == organization.id


@pytest.mark.asyncio
async def test_register_oidc_provider_requires_org_membership_for_org_provider(monkeypatch) -> None:
    sso_client, _, organization, _ = build_client()
    outsider = build_individual(email="outsider@example.com", name="Outsider")
    sso_client.organization_adapter.add_member(
        build_member(
            organization_id=organization.id,
            individual_id=uuid4(),
            role="member",
        ),
    )
    monkeypatch.setattr("belgie_sso.client.discover_oidc_configuration", AsyncMock())

    with pytest.raises(HTTPException, match="organization membership is required"):
        await replace(sso_client, current_individual=outsider).register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )


@pytest.mark.asyncio
async def test_org_provider_limit_counts_existing_org_providers_without_org_admin_listing(monkeypatch) -> None:
    sso_client, adapter, organization, _ = build_client()
    sso_client.organization_adapter.member.role = "member"
    sso_client.settings.providers_limit = 1
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
    await adapter.create_provider(
        sso_client.client.db,
        organization_id=organization.id,
        created_by_individual_id=sso_client.current_individual.id,
        provider_type="oidc",
        provider_id="existing",
        issuer="https://idp.example.com",
        oidc_config=None,
        saml_config=None,
    )

    with pytest.raises(HTTPException, match="provider limit reached"):
        await sso_client.register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )


@pytest.mark.asyncio
async def test_create_domain_challenge_requires_org_provider_owner_even_for_org_members() -> None:
    sso_client, sso_adapter, organization, _ = build_client()
    provider = await sso_adapter.create_provider(
        sso_client.client.db,
        organization_id=organization.id,
        created_by_individual_id=sso_client.current_individual.id,
        provider_type="oidc",
        provider_id="acme",
        issuer="https://idp.example.com",
        domain="example.com",
        oidc_config=None,
        saml_config=None,
    )
    org_member = build_individual(email="member@example.com", name="Member")
    sso_client.organization_adapter.add_member(
        build_member(
            organization_id=organization.id,
            individual_id=org_member.id,
            role="member",
        ),
    )
    member_client = replace(sso_client, current_individual=org_member)

    with pytest.raises(HTTPException, match="provider owner access is required"):
        await member_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")


@pytest.mark.asyncio
async def test_create_domain_challenge_requires_org_membership_for_provider_owner() -> None:
    sso_client, sso_adapter, organization, _ = build_client()
    provider = await sso_adapter.create_provider(
        sso_client.client.db,
        organization_id=organization.id,
        created_by_individual_id=sso_client.current_individual.id,
        provider_type="oidc",
        provider_id="acme",
        issuer="https://idp.example.com",
        domain="example.com",
        oidc_config=None,
        saml_config=None,
    )
    sso_client.organization_adapter.add_member(
        build_member(
            organization_id=organization.id,
            individual_id=uuid4(),
            role="member",
        ),
    )
    sso_client.organization_adapter.members.pop((organization.id, sso_client.current_individual.id), None)

    with pytest.raises(HTTPException, match="organization membership is required"):
        await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")


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
async def test_verify_domain_requires_org_provider_owner_even_for_org_members(monkeypatch) -> None:
    sso_client, sso_adapter, organization, _ = build_client()
    provider = await sso_adapter.create_provider(
        sso_client.client.db,
        organization_id=organization.id,
        created_by_individual_id=sso_client.current_individual.id,
        provider_type="oidc",
        provider_id="acme",
        issuer="https://idp.example.com",
        domain="example.com",
        oidc_config=None,
        saml_config=None,
    )
    challenge = await sso_client.create_domain_challenge(provider_id=provider.provider_id, domain="example.com")
    monkeypatch.setattr(
        "belgie_sso.client.lookup_txt_records",
        AsyncMock(return_value=[challenge.record_value]),
    )
    org_member = build_individual(email="member@example.com", name="Member")
    sso_client.organization_adapter.add_member(
        build_member(
            organization_id=organization.id,
            individual_id=org_member.id,
            role="member",
        ),
    )
    member_client = replace(sso_client, current_individual=org_member)

    with pytest.raises(HTTPException, match="provider owner access is required"):
        await member_client.verify_domain(provider_id=provider.provider_id, domain="example.com")


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
async def test_register_oidc_provider_maps_discovery_unsupported_token_auth_method_to_http_exception(
    monkeypatch,
) -> None:
    sso_client, _, _, _ = build_client()
    monkeypatch.setattr(
        "belgie_sso.client.discover_oidc_configuration",
        AsyncMock(
            side_effect=DiscoveryError(
                "unsupported_token_auth_method",
                "OIDC provider does not support client_secret_basic or client_secret_post for the token endpoint",
                details={
                    "requested_method": "client_secret_basic",
                    "supported_methods": ["private_key_jwt"],
                },
            ),
        ),
    )

    with pytest.raises(
        HTTPException,
        match=(
            "incompatible OIDC provider: "
            "OIDC provider does not support client_secret_basic or client_secret_post for the token endpoint"
        ),
    ) as exc_info:
        await sso_client.register_oidc_provider(
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
        )

    assert exc_info.value.status_code == 400


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


@pytest.mark.asyncio
async def test_update_oidc_provider_maps_discovery_unsupported_token_auth_method_to_http_exception(
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
                DiscoveryError(
                    "unsupported_token_auth_method",
                    "OIDC provider does not support client_secret_basic or client_secret_post for the token endpoint",
                    details={
                        "requested_method": "client_secret_basic",
                        "supported_methods": ["private_key_jwt"],
                    },
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

    with pytest.raises(
        HTTPException,
        match=(
            "incompatible OIDC provider: "
            "OIDC provider does not support client_secret_basic or client_secret_post for the token endpoint"
        ),
    ) as exc_info:
        await sso_client.update_oidc_provider(
            provider_id="acme",
            issuer="https://idp.example.com/updated",
        )

    assert exc_info.value.status_code == 400
