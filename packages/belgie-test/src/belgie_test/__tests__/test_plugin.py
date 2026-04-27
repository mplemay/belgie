from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from tempfile import gettempdir
from typing import TYPE_CHECKING, get_args, get_type_hints
from uuid import uuid4

import pytest
import pytest_asyncio
from belgie_alchemy.__tests__.fixtures.core.database import get_test_engine, get_test_session_factory
from belgie_alchemy.__tests__.fixtures.core.models import Account, Individual, OAuthAccount, OAuthState, Session
from belgie_alchemy.__tests__.fixtures.organization.models import (
    Organization as OrganizationRow,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.__tests__.fixtures.team.models import Team
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.organization import OrganizationAdapter
from belgie_core.core.belgie import Belgie
from belgie_core.core.settings import BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie_organization.settings import Organization
from belgie_test import (
    OrganizationTestUtils as BelgieOrganizationTestUtils,
    TestCookie as BelgieTestCookie,
    TestUtils as BelgieTestUtils,
    TestUtilsPlugin as BelgieTestUtilsPlugin,
)
from fastapi import FastAPI, Request
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_ = Team


@pytest.fixture
def sqlite_database() -> str:
    return f"{gettempdir()}/belgie_test_utils_{uuid4().hex}.db"


@pytest_asyncio.fixture
async def db_engine(sqlite_database: str) -> AsyncGenerator[AsyncEngine, None]:
    engine = await get_test_engine(sqlite_database)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return await get_test_session_factory(db_engine)


@pytest_asyncio.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def auth_settings() -> BelgieSettings:
    return BelgieSettings(
        secret="test-utils-secret",
        base_url="http://testserver",
        session=SessionSettings(max_age=3600, update_age=900),
        cookie=CookieSettings(
            name="test_session",
            secure=False,
            http_only=True,
            same_site="lax",
        ),
        urls=URLSettings(signin_redirect="/dashboard", signout_redirect="/"),
    )


@pytest.fixture
def database(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with db_session_factory() as session:
            yield session

    return get_db


@pytest.fixture
def adapter() -> BelgieAdapter:
    return BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,  # ty: ignore[invalid-argument-type]
    )


@pytest.fixture
def organization_adapter() -> OrganizationAdapter:
    return OrganizationAdapter(
        organization=OrganizationRow,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
    )


@pytest.fixture
def belgie(
    auth_settings: BelgieSettings,
    adapter: BelgieAdapter,
    database: Callable[[], AsyncGenerator[AsyncSession, None]],
) -> Belgie:
    return Belgie(settings=auth_settings, adapter=adapter, database=database)


def test_plugin_exposes_helpers_and_no_routes(belgie: Belgie) -> None:
    test = belgie.add_plugin(BelgieTestUtils())

    assert isinstance(test, BelgieTestUtilsPlugin)
    assert test.create_individual is not None
    assert test.save_individual is not None
    assert test.delete_individual is not None
    assert test.login is not None
    assert test.get_auth_headers is not None
    assert test.get_cookies is not None
    assert test.organization is None
    assert not hasattr(test, "capture_verification_token")
    assert not hasattr(test, "get_otp")
    assert not hasattr(test, "clear_otps")

    app = FastAPI()
    app.include_router(belgie.router)
    client = TestClient(app)

    assert client.get("/auth/test-utils").status_code == 404


def test_public_exports_include_organization_test_utils() -> None:
    belgie_test_package = import_module("belgie_test")
    belgie_test_module = import_module("belgie.test")

    assert belgie_test_package.OrganizationTestUtils is BelgieOrganizationTestUtils
    assert belgie_test_module.OrganizationTestUtils is BelgieOrganizationTestUtils
    assert "OrganizationTestUtils" in belgie_test_package.__all__
    assert "OrganizationTestUtils" in belgie_test_module.__all__


def test_cookie_type_restricts_browser_same_site_values() -> None:
    same_site = get_type_hints(BelgieTestCookie)["sameSite"]

    assert set(get_args(same_site)) == {"Lax", "Strict", "None"}


def test_plugin_captures_otps_when_enabled(belgie: Belgie) -> None:
    test = belgie.add_plugin(BelgieTestUtils(capture_otp=True))

    assert hasattr(test, "capture_verification_token")
    assert hasattr(test, "get_otp")
    assert hasattr(test, "clear_otps")

    test.capture_verification_token("example.com", "123456")  # type: ignore[attr-defined]

    assert test.get_otp("example.com") == "123456"  # type: ignore[attr-defined]

    test.clear_otps()  # type: ignore[attr-defined]

    assert test.get_otp("example.com") is None  # type: ignore[attr-defined]


def test_otp_capture_is_instance_scoped(belgie: Belgie) -> None:
    first = belgie.add_plugin(BelgieTestUtils(capture_otp=True))
    second = belgie.add_plugin(BelgieTestUtils(capture_otp=True))

    first.capture_verification_token("example.com", "123456")  # type: ignore[attr-defined]

    assert first.get_otp("example.com") == "123456"  # type: ignore[attr-defined]
    assert second.get_otp("example.com") is None  # type: ignore[attr-defined]


def test_create_individual_defaults_and_overrides(belgie: Belgie) -> None:
    test = belgie.add_plugin(BelgieTestUtils())

    default = test.create_individual()
    assert default.email.endswith("@example.com")
    assert default.name == "Test Individual"
    assert default.email_verified_at is not None
    assert default.scopes == []

    custom = test.create_individual(
        email="custom@example.com",
        name="Custom Individual",
        email_verified=False,
        scopes=["read"],
        custom_field="custom value",
    )
    assert custom.email == "custom@example.com"
    assert custom.name == "Custom Individual"
    assert custom.email_verified_at is None
    assert custom.scopes == ["read"]
    assert custom.custom_fields == {"custom_field": "custom value"}


@pytest.mark.asyncio
async def test_create_individual_is_unsaved_until_save(belgie: Belgie, db_session: AsyncSession) -> None:
    test = belgie.add_plugin(BelgieTestUtils())

    data = test.create_individual(email="factory@example.com")

    assert await belgie.adapter.get_individual_by_email(db_session, data.email) is None


@pytest.mark.asyncio
async def test_save_and_delete_individual(belgie: Belgie, db_session: AsyncSession) -> None:
    test = belgie.add_plugin(BelgieTestUtils())
    data = test.create_individual(
        email="saved@example.com",
        scopes=["openid", "email"],
        custom_field="stored",
    )

    individual = await test.save_individual(db_session, data)

    assert isinstance(individual, Individual)
    assert individual.email == "saved@example.com"
    assert individual.scopes == ["openid", "email"]
    assert individual.custom_field == "stored"

    assert await test.delete_individual(db_session, individual.id) is True
    assert await belgie.adapter.get_individual_by_id(db_session, individual.id) is None


@pytest.mark.asyncio
async def test_login_returns_session_headers_cookies_and_token(belgie: Belgie, db_session: AsyncSession) -> None:
    test = belgie.add_plugin(BelgieTestUtils())
    individual = await test.save_individual(db_session, test.create_individual(email="login@example.com"))

    result = await test.login(db_session, individual_id=individual.id)

    assert result.individual.id == individual.id
    assert result.session.individual_id == individual.id
    assert result.token == str(result.session.id)
    assert result.headers == {"cookie": f"test_session={result.session.id}"}
    assert result.cookies[0]["name"] == "test_session"
    assert result.cookies[0]["value"] == str(result.session.id)
    assert result.cookies[0]["domain"] == "testserver"
    assert result.cookies[0]["path"] == "/"
    assert result.cookies[0]["httpOnly"] is True
    assert result.cookies[0]["secure"] is False
    assert result.cookies[0]["sameSite"] == "Lax"
    assert "expires" in result.cookies[0]


@pytest.mark.asyncio
async def test_get_auth_headers_authenticates_fastapi_route(
    belgie: Belgie,
    db_session: AsyncSession,
) -> None:
    test = belgie.add_plugin(BelgieTestUtils())
    individual = await test.save_individual(
        db_session,
        test.create_individual(email="route@example.com", scopes=["openid", "email"]),
    )

    app = FastAPI()
    app.include_router(belgie.router)

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | list[str]]:
        current = await belgie.__call__(db_session).get_individual(SecurityScopes(scopes=["openid"]), request)
        return {"id": str(current.id), "email": current.email, "scopes": current.scopes}

    client = TestClient(app)
    response = client.get("/me", headers=await test.get_auth_headers(db_session, individual_id=individual.id))

    assert response.status_code == 200, response.json()
    assert response.json() == {"id": str(individual.id), "email": "route@example.com", "scopes": ["openid", "email"]}


@pytest.mark.asyncio
async def test_get_cookies_returns_browser_cookie_with_custom_domain(
    belgie: Belgie,
    db_session: AsyncSession,
) -> None:
    test = belgie.add_plugin(BelgieTestUtils())
    individual = await test.save_individual(db_session, test.create_individual(email="cookies@example.com"))

    cookies = await test.get_cookies(db_session, individual_id=individual.id, domain="custom.example.com")

    assert cookies[0]["name"] == "test_session"
    assert cookies[0]["domain"] == "custom.example.com"
    assert cookies[0]["value"]


@pytest.mark.asyncio
async def test_get_cookies_mirrors_cookie_settings(
    adapter: BelgieAdapter,
    database: Callable[[], AsyncGenerator[AsyncSession, None]],
    db_session: AsyncSession,
) -> None:
    settings = BelgieSettings(
        secret="test-utils-secret",
        base_url="https://auth.example.com",
        session=SessionSettings(max_age=7200, update_age=900),
        cookie=CookieSettings(
            name="secure_session",
            secure=True,
            http_only=False,
            same_site="strict",
        ),
        urls=URLSettings(signin_redirect="/dashboard", signout_redirect="/"),
    )
    belgie = Belgie(settings=settings, adapter=adapter, database=database)
    test = belgie.add_plugin(BelgieTestUtils())
    individual = await test.save_individual(db_session, test.create_individual(email="secure-cookie@example.com"))

    cookies = await test.get_cookies(db_session, individual_id=individual.id)

    assert cookies[0]["name"] == "secure_session"
    assert cookies[0]["domain"] == "auth.example.com"
    assert cookies[0]["path"] == "/"
    assert cookies[0]["httpOnly"] is False
    assert cookies[0]["secure"] is True
    assert cookies[0]["sameSite"] == "Strict"
    assert cookies[0]["expires"] > int(datetime.now(UTC).timestamp())


@pytest.mark.asyncio
async def test_login_rejects_missing_individual(belgie: Belgie, db_session: AsyncSession) -> None:
    test = belgie.add_plugin(BelgieTestUtils())

    with pytest.raises(ValueError, match="individual not found"):
        await test.login(db_session, individual_id=uuid4())


@pytest.mark.asyncio
async def test_organization_factory_defaults_overrides_and_unsaved(
    belgie: Belgie,
    organization_adapter: OrganizationAdapter,
    db_session: AsyncSession,
) -> None:
    test = belgie.add_plugin(BelgieTestUtils())
    belgie.add_plugin(Organization(adapter=organization_adapter))

    organization_helpers = test.organization
    assert isinstance(organization_helpers, BelgieOrganizationTestUtils)

    default = organization_helpers.create_organization()
    assert default.name == "Test Organization"
    assert default.slug.startswith("test-organization-")
    assert default.logo is None

    custom = organization_helpers.create_organization(name="Custom Org", slug="custom-org", logo="https://logo.test")
    assert custom.name == "Custom Org"
    assert custom.slug == "custom-org"
    assert custom.logo == "https://logo.test"
    assert await organization_adapter.get_organization_by_slug(db_session, custom.slug) is None


@pytest.mark.asyncio
async def test_organization_helpers_are_lazy_and_adapter_backed(
    belgie: Belgie,
    organization_adapter: OrganizationAdapter,
    db_session: AsyncSession,
) -> None:
    test = belgie.add_plugin(BelgieTestUtils())
    assert test.organization is None

    belgie.add_plugin(Organization(adapter=organization_adapter))

    organization_helpers = test.organization
    assert organization_helpers is not None

    individual = await test.save_individual(db_session, test.create_individual(email="member@example.com"))
    organization_data = organization_helpers.create_organization(name="Acme Corp", slug="acme")
    organization = await organization_helpers.save_organization(db_session, organization_data)
    member = await organization_helpers.add_member(
        db_session,
        individual_id=individual.id,
        organization_id=organization.id,
        role="admin",
    )

    assert organization.name == "Acme Corp"
    assert organization.slug == "acme"
    assert member.individual_id == individual.id
    assert member.organization_id == organization.id
    assert member.role == "admin"

    assert await organization_helpers.delete_organization(db_session, organization.id) is True
    assert await organization_adapter.get_organization_by_id(db_session, organization.id) is None


@pytest.mark.asyncio
async def test_delete_organization_removes_related_members_and_invitations(
    belgie: Belgie,
    organization_adapter: OrganizationAdapter,
    db_session: AsyncSession,
) -> None:
    test = belgie.add_plugin(BelgieTestUtils())
    belgie.add_plugin(Organization(adapter=organization_adapter))

    organization_helpers = test.organization
    assert organization_helpers is not None

    owner = await test.save_individual(db_session, test.create_individual(email="owner@example.com"))
    invitee = await test.save_individual(db_session, test.create_individual(email="invitee@example.com"))
    organization = await organization_helpers.save_organization(
        db_session,
        organization_helpers.create_organization(name="Cascade Org", slug="cascade-org"),
    )
    member = await organization_helpers.add_member(
        db_session,
        individual_id=owner.id,
        organization_id=organization.id,
    )
    invitation = await organization_adapter.create_invitation(
        db_session,
        organization_id=organization.id,
        team_id=None,
        email=invitee.email,
        role="member",
        inviter_individual_id=owner.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    assert member in await organization_adapter.list_members(db_session, organization_id=organization.id)
    assert invitation in await organization_adapter.list_invitations(db_session, organization_id=organization.id)

    assert await organization_helpers.delete_organization(db_session, organization.id) is True
    assert await organization_adapter.get_organization_by_id(db_session, organization.id) is None
    assert await organization_adapter.get_member_by_id(db_session, member.id) is None
    assert await organization_adapter.get_invitation(db_session, invitation.id) is None
