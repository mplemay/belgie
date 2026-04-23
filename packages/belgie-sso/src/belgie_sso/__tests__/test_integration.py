# ruff: noqa: ARG002, ARG005

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from belgie_alchemy.__tests__.fixtures.core.models import Account, Individual, OAuthAccount, OAuthState, Session
from belgie_alchemy.__tests__.fixtures.organization.models import (
    Organization as OrganizationModel,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.__tests__.fixtures.team.models import Team, TeamMember  # noqa: F401
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.organization import OrganizationAdapter
from belgie_alchemy.sso import SSOAdapter, SSODomainMixin, SSOProviderMixin
from belgie_core import Belgie, BelgieClient, BelgieSettings
from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo
from belgie_organization import Organization
from belgie_proto.sso import OIDCProviderConfig
from belgie_sso import EnterpriseSSO
from belgie_sso.client import SSOClient
from belgie_sso.discovery import OIDCDiscoveryResult
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class SSOProvider(DataclassBase, PrimaryKeyMixin, TimestampMixin, SSOProviderMixin):
    pass


class SSODomain(DataclassBase, PrimaryKeyMixin, TimestampMixin, SSODomainMixin):
    pass


class FakeOIDCTransport:
    def __init__(self) -> None:
        self.config = SimpleNamespace(use_pkce=True)

    def should_use_nonce(self, scopes):
        return True

    async def generate_authorization_url(self, state: str, **kwargs: object) -> str:
        return f"https://idp.example.com/authorize?state={state}"

    async def resolve_server_metadata(self) -> dict[str, str]:
        return {"issuer": "https://idp.example.com"}

    def validate_issuer_parameter(self, issuer: str | None, metadata: dict[str, str]) -> None:
        return None

    async def exchange_code_for_tokens(self, code: str, *, code_verifier: str | None = None) -> OAuthTokenSet:
        return OAuthTokenSet(
            access_token=f"access-{code}",
            refresh_token="refresh-token",
            token_type="Bearer",
            scope="openid email profile",
            id_token="id-token",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token_expires_at=None,
            raw={"access_token": f"access-{code}", "refresh_token": "refresh-token"},
        )

    async def fetch_provider_profile(self, token_set: OAuthTokenSet, *, nonce: str | None = None) -> OAuthUserInfo:
        return OAuthUserInfo(
            provider_account_id="oidc-user-1",
            email="person@dept.example.com",
            email_verified=True,
            name="Person Example",
            raw={
                "sub": "oidc-user-1",
                "email": "person@dept.example.com",
                "email_verified": True,
                "name": "Person Example",
            },
        )


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    database_path = tmp_path / "belgie-sso.sqlite3"
    engine = create_async_engine(
        URL.create("sqlite+aiosqlite", database=str(database_path)),
        echo=False,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(DataclassBase.metadata.create_all)

    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_enterprise_sso_flow_assigns_user_to_existing_org(monkeypatch, session_factory) -> None:
    core_adapter = BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    )
    organization_adapter = OrganizationAdapter(
        organization=OrganizationModel,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
    )
    sso_adapter = SSOAdapter(
        sso_provider=SSOProvider,
        sso_domain=SSODomain,
    )

    settings = BelgieSettings(secret="secret", base_url="http://localhost:8000")

    async def database():
        async with session_factory() as session:
            yield session

    belgie = Belgie(
        settings=settings,
        adapter=core_adapter,
        database=database,
    )
    belgie.add_plugin(Organization(adapter=organization_adapter))
    sso_settings = EnterpriseSSO(adapter=sso_adapter)
    sso_plugin = belgie.add_plugin(sso_settings)

    async with session_factory() as session:
        owner = await core_adapter.create_individual(
            session,
            email="owner@example.com",
            name="Owner",
            email_verified_at=datetime.now(UTC),
        )
        organization = await organization_adapter.create_organization(
            session,
            name="Acme",
            slug="acme",
        )
        await organization_adapter.create_member(
            session,
            organization_id=organization.id,
            individual_id=owner.id,
            role="owner",
        )

        management_client = SSOClient(
            client=BelgieClient(
                db=session,
                adapter=core_adapter,
                session_manager=belgie.session_manager,
                cookie_settings=belgie.settings.cookie,
            ),
            settings=sso_settings,
            organization_adapter=organization_adapter,
            current_individual=owner,
        )

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

        provider = await management_client.register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            domains=["example.com"],
        )
        domain = (await sso_adapter.list_domains_for_provider(session, sso_provider_id=provider.id))[0]
        await sso_adapter.update_domain(session, domain_id=domain.id, verified_at=datetime.now(UTC))

    monkeypatch.setattr(sso_plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    app.include_router(belgie.router)
    client = TestClient(app, base_url="https://testserver.local")

    signin_response = client.get(
        "/auth/provider/sso/signin?email=person@dept.example.com",
        follow_redirects=False,
    )

    assert signin_response.status_code == 302
    state = parse_qs(urlparse(signin_response.headers["location"]).query)["state"][0]

    callback_response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/dashboard"

    async with session_factory() as session:
        created_user = await core_adapter.get_individual_by_email(session, "person@dept.example.com")
        assert created_user is not None
        member = await organization_adapter.get_member(
            session,
            organization_id=organization.id,
            individual_id=created_user.id,
        )
        assert member is not None
        assert member.role == "member"
