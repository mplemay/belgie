from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.security import SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession

from __tests__.auth.fixtures.models import Account, OAuthState, Session, User
from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.core.auth import Auth
from belgie.auth.core.settings import AuthSettings, CookieSettings, GoogleOAuthSettings, SessionSettings, URLSettings
from belgie.auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(
        secret="test-secret-key",  # noqa: S106
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
        google=GoogleOAuthSettings(
            client_id="test-client-id",
            client_secret="test-client-secret",  # noqa: S106
            redirect_uri="http://localhost:8000/auth/callback/google",
            scopes=["openid", "email", "profile"],
        ),
        urls=URLSettings(
            signin_redirect="/dashboard",
            signout_redirect="/",
        ),
    )


@pytest.fixture
def adapter(db_session: AsyncSession) -> AlchemyAdapter:
    async def get_db() -> AsyncSession:
        return db_session

    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
        db_dependency=get_db,
    )


@pytest.fixture
def auth(auth_settings: AuthSettings, adapter: AlchemyAdapter) -> Auth:
    return Auth(settings=auth_settings, adapter=adapter)


def test_auth_initialization(auth: Auth, auth_settings: AuthSettings) -> None:
    assert auth.settings == auth_settings
    assert auth.adapter is not None
    assert auth.session_manager is not None
    assert auth.providers is not None
    assert isinstance(auth.providers, dict)
    assert auth.router is not None


def test_auth_session_manager_configuration(auth: Auth) -> None:
    assert auth.session_manager.max_age == 3600
    assert auth.session_manager.update_age == 900


def test_auth_provider_management(auth: Auth) -> None:
    # Test list_providers()
    provider_ids = auth.list_providers()
    assert isinstance(provider_ids, list)
    assert "google" in provider_ids

    # Test get_provider()
    google_provider = auth.get_provider("google")
    assert google_provider is not None
    assert google_provider.provider_id == "google"

    # Cast to GoogleOAuthProvider to access settings
    assert isinstance(google_provider, GoogleOAuthProvider)
    assert google_provider.settings.client_id == "test-client-id"
    assert google_provider.settings.client_secret == "test-client-secret"  # noqa: S105
    assert google_provider.settings.redirect_uri == "http://localhost:8000/auth/callback/google"
    assert google_provider.settings.scopes == ["openid", "email", "profile"]

    # Test get_provider() with non-existent provider
    non_existent = auth.get_provider("nonexistent")
    assert non_existent is None


def test_register_provider_replacement(auth: Auth) -> None:
    """Test that registering a provider with the same ID replaces the existing one."""
    # Verify initial provider exists
    original_provider = auth.get_provider("google")
    assert original_provider is not None
    assert isinstance(original_provider, GoogleOAuthProvider)
    assert original_provider.settings.client_id == "test-client-id"

    # Create and register a replacement provider with different settings
    custom_settings = GoogleProviderSettings(
        client_id="custom-client-id",
        client_secret="custom-secret",  # noqa: S106
        redirect_uri="https://custom.com/callback",
        scopes=["openid", "email"],
    )
    custom_provider = GoogleOAuthProvider(settings=custom_settings)
    auth.register_provider(custom_provider)

    # Verify the provider was replaced
    replaced_provider = auth.get_provider("google")
    assert replaced_provider is not None
    assert replaced_provider is custom_provider  # Should be the same instance
    assert isinstance(replaced_provider, GoogleOAuthProvider)
    assert replaced_provider.settings.client_id == "custom-client-id"
    assert replaced_provider.settings.redirect_uri == "https://custom.com/callback"
    assert replaced_provider.settings.scopes == ["openid", "email"]

    # Verify list_providers still has only one google provider
    provider_ids = auth.list_providers()
    assert provider_ids.count("google") == 1


def test_auth_router_created(auth: Auth) -> None:
    assert auth.router.prefix == "/auth"
    assert "auth" in auth.router.tags


@pytest.mark.asyncio
async def test_get_user_from_session_valid(auth: Auth, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    retrieved_user = await auth.get_user_from_session(db_session, session.id)

    assert retrieved_user is not None
    assert retrieved_user.id == user.id
    assert retrieved_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_get_user_from_session_invalid(auth: Auth, db_session: AsyncSession) -> None:
    user = await auth.get_user_from_session(db_session, uuid4())
    assert user is None


@pytest.mark.asyncio
async def test_get_user_from_session_expired(auth: Auth, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    expired_session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    retrieved_user = await auth.get_user_from_session(db_session, expired_session.id)
    assert retrieved_user is None


@pytest.mark.asyncio
async def test_sign_out_success(auth: Auth, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    result = await auth.sign_out(db_session, session.id)
    assert result is True

    retrieved_session = await auth.session_manager.get_session(db_session, session.id)
    assert retrieved_session is None


@pytest.mark.asyncio
async def test_sign_out_nonexistent_session(auth: Auth, db_session: AsyncSession) -> None:
    result = await auth.sign_out(db_session, uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_user_dependency_authenticated(auth: Auth, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes()

    retrieved_user = await auth.user(security_scopes, request, db_session)

    assert retrieved_user.id == user.id
    assert retrieved_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_user_dependency_missing_cookie(auth: Auth, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {}

    security_scopes = SecurityScopes()

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]
    assert "not authenticated" in str(exc_info.value.detail)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_dependency_invalid_session(auth: Auth, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(uuid4())}

    security_scopes = SecurityScopes()

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_dependency_expired_session(auth: Auth, db_session: AsyncSession) -> None:
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
async def test_user_dependency_with_valid_scopes(auth: Auth, db_session: AsyncSession) -> None:
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
async def test_user_dependency_with_insufficient_scopes(auth: Auth, db_session: AsyncSession) -> None:
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
async def test_user_dependency_scopes_required_but_user_has_no_scopes(auth: Auth, db_session: AsyncSession) -> None:
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
async def test_session_dependency_valid(auth: Auth, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(session.id)}

    retrieved_session = await auth.session(request, db_session)

    assert retrieved_session.id == session.id
    assert retrieved_session.user_id == user.id


@pytest.mark.asyncio
async def test_session_dependency_missing_cookie(auth: Auth, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]
    assert "not authenticated" in str(exc_info.value.detail)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_session_dependency_invalid_session(auth: Auth, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: str(uuid4())}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_session_dependency_invalid_uuid_format(auth: Auth, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.cookie.name: "not-a-uuid"}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]
