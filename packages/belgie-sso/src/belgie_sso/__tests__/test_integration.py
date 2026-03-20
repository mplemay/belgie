from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from belgie_alchemy.__tests__.fixtures.core.models import Account, OAuthState, Session, User
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
from belgie_organization import Organization as OrganizationPlugin
from belgie_proto.sso import OIDCProviderConfig
from belgie_sso import EnterpriseSSO
from belgie_sso.client import SSOClient
from belgie_sso.discovery import OIDCDiscoveryResult
from belgie_sso.plugin import TokenResponse
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class SSOProvider(DataclassBase, PrimaryKeyMixin, TimestampMixin, SSOProviderMixin):
    pass


class SSODomain(DataclassBase, PrimaryKeyMixin, TimestampMixin, SSODomainMixin):
    pass


@pytest_asyncio.fixture
async def session_factory(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
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
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )
    organization_adapter = OrganizationAdapter(
        core=core_adapter,
        organization=OrganizationModel,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
    )
    sso_adapter = SSOAdapter(
        sso_provider=SSOProvider,
        sso_domain=SSODomain,
    )

    settings = BelgieSettings(secret="secret", base_url="http://localhost:8000")

    async def database() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    belgie = Belgie(
        settings=settings,
        adapter=core_adapter,
        database=database,
    )
    belgie.add_plugin(
        OrganizationPlugin(
            adapter=organization_adapter,
        ),
    )
    sso_settings = EnterpriseSSO(adapter=sso_adapter)
    sso_plugin = belgie.add_plugin(sso_settings)

    async with session_factory() as session:
        owner = await core_adapter.create_user(
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
            user_id=owner.id,
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
            adapter=sso_adapter,
            organization_adapter=organization_adapter,
            current_user=owner,
        )

        monkeypatch.setattr(
            "belgie_sso.client.discover_oidc_configuration",
            AsyncMock(
                return_value=OIDCDiscoveryResult(
                    issuer="https://idp.example.com",
                    config=OIDCProviderConfig(
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
        monkeypatch.setattr(
            "belgie_sso.client.lookup_txt_records",
            AsyncMock(return_value=[domain.verification_token]),
        )
        await management_client.verify_domain(provider_id="acme", domain="example.com")

    monkeypatch.setattr(
        sso_plugin,
        "_exchange_code_for_tokens",
        AsyncMock(
            return_value=TokenResponse(
                access_token="access-token",
                token_type="Bearer",
                refresh_token="refresh-token",
                scope="openid email profile",
                id_token="id-token",
                expires_at=None,
            ),
        ),
    )
    monkeypatch.setattr(
        sso_plugin,
        "get_user_info",
        AsyncMock(
            return_value={
                "sub": "oidc-user-1",
                "email": "person@example.com",
                "email_verified": True,
                "name": "Person Example",
            },
        ),
    )

    app = FastAPI()
    app.include_router(belgie.router)

    signin_response = TestClient(app).get(
        "/auth/provider/sso/signin?email=person@example.com",
        follow_redirects=False,
    )

    assert signin_response.status_code == 302
    state = parse_qs(urlparse(signin_response.headers["location"]).query)["state"][0]

    callback_response = TestClient(app).get(
        f"/auth/provider/sso/callback/acme?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/dashboard"

    async with session_factory() as session:
        created_user = await core_adapter.get_user_by_email(session, "person@example.com")
        assert created_user is not None
        member = await organization_adapter.get_member(
            session,
            organization_id=organization.id,
            user_id=created_user.id,
        )
        assert member is not None
        assert member.role == "member"
