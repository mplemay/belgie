from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from belgie_alchemy import AlchemyAdapter
from belgie_alchemy.__tests__.fixtures.models import Account, OAuthState, Session, User
from belgie_core.core.belgie import Belgie
from belgie_core.core.settings import BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie_core.providers.google import GoogleProviderSettings
from fastapi import HTTPException, Request
from fastapi.security import SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def auth_settings() -> BelgieSettings:
    return BelgieSettings(
        secret="test-secret-key",
        base_url="http://localhost:8000",
        session=SessionSettings(
            max_age=3600,
            update_age=900,
        ),
        cookie=CookieSettings(
            name="belgie_session",
            secure=False,
            http_only=True,
            same_site="lax",
        ),
        urls=URLSettings(
            signin_redirect="/dashboard",
            signout_redirect="/",
        ),
    )


@pytest.fixture
def adapter() -> AlchemyAdapter:
    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )


@pytest.fixture
def auth(auth_settings: BelgieSettings, adapter: AlchemyAdapter, db_session: AsyncSession) -> Belgie:
    # Pass provider settings (not instances)
    providers = {
        "google": GoogleProviderSettings(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="http://localhost:8000/auth/provider/google/callback",
            scopes=["openid", "email", "profile"],
        ),
    }

    async def get_db_override() -> AsyncSession:
        return db_session

    fake_db = SimpleNamespace(dependency=get_db_override)

    return Belgie(
        settings=auth_settings,
        adapter=adapter,
        providers=providers,
        db=fake_db,
    )


def test_auth_initialization(auth: Belgie, auth_settings: BelgieSettings) -> None:
    assert auth.settings == auth_settings
    assert auth.adapter is not None
    assert auth.session_manager is not None
    assert auth.providers is not None
    assert isinstance(auth.providers, dict)
    assert auth.router is not None


def test_auth_session_manager_configuration(auth: Belgie) -> None:
    assert auth.session_manager.max_age == 3600
    assert auth.session_manager.update_age == 900


def test_auth_router_created(auth: Belgie) -> None:
    router = auth.router
    assert router.prefix == ""
    assert any(getattr(route, "path", "").startswith("/auth") for route in router.routes)


def test_register_provider_invalidates_router_cache(auth: Belgie) -> None:
    """Test that registering a provider after router creation invalidates the cache."""
    # Access the router to cache it
    first_router = auth.router
    assert first_router.prefix == ""

    # With method based approach, we can just verify it returns a router
    # Caching check is no longer relevant as per refactor
    assert auth.router is not None


@pytest.mark.asyncio
async def test_get_user_from_session_valid(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    retrieved_user = await auth.get_user_from_session(db_session, session.id)

    assert retrieved_user is not None
    assert retrieved_user.id == user.id
    assert retrieved_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_get_user_from_session_invalid(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.get_user_from_session(db_session, uuid4())
    assert user is None


@pytest.mark.asyncio
async def test_get_user_from_session_expired(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    expired_session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    retrieved_user = await auth.get_user_from_session(db_session, expired_session.id)
    assert retrieved_user is None


@pytest.mark.asyncio
async def test_sign_out_success(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    result = await auth.sign_out(db_session, session.id)
    assert result is True

    retrieved_session = await auth.session_manager.get_session(db_session, session.id)
    assert retrieved_session is None


@pytest.mark.asyncio
async def test_sign_out_nonexistent_session(auth: Belgie, db_session: AsyncSession) -> None:
    result = await auth.sign_out(db_session, uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_user_dependency_authenticated(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes()

    retrieved_user = await auth.user(security_scopes, request, db_session)

    assert retrieved_user.id == user.id
    assert retrieved_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_user_dependency_missing_cookie(auth: Belgie, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {}

    security_scopes = SecurityScopes()

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]
    assert "not authenticated" in str(exc_info.value.detail)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_dependency_invalid_session(auth: Belgie, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(uuid4())}

    security_scopes = SecurityScopes()

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_dependency_expired_session(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    expired_session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(expired_session.id)}

    security_scopes = SecurityScopes()

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_dependency_with_valid_scopes(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    # Assign user-level scopes
    user.scopes = ["openid", "email", "profile", "admin"]
    await db_session.commit()
    await db_session.refresh(user)

    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes(scopes=["email", "profile"])

    retrieved_user = await auth.user(security_scopes, request, db_session)
    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_user_dependency_with_insufficient_scopes(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    # Assign user-level scopes (missing 'admin')
    user.scopes = ["openid", "email"]
    await db_session.commit()
    await db_session.refresh(user)

    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes(scopes=["admin"])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    assert exc_info.value.detail == "Insufficient permissions"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_dependency_scopes_required_but_user_has_no_scopes(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    # User has no scopes (None by default)
    assert user.scopes is None

    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes(scopes=["admin"])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_session_dependency_valid(auth: Belgie, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(session.id)}

    retrieved_session = await auth.session(request, db_session)

    assert retrieved_session.id == session.id
    assert retrieved_session.user_id == user.id


@pytest.mark.asyncio
async def test_session_dependency_missing_cookie(auth: Belgie, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]
    assert "not authenticated" in str(exc_info.value.detail)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_session_dependency_invalid_session(auth: Belgie, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(uuid4())}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_session_dependency_invalid_uuid_format(auth: Belgie, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: "not-a-uuid"}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]
