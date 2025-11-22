from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
import respx
from fastapi import HTTPException, Request
from fastapi.security import SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession

from __tests__.auth.fixtures.models import Account, OAuthState, Session, User
from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.core.auth import Auth
from belgie.auth.core.exceptions import InvalidStateError, OAuthError
from belgie.auth.core.settings import AuthSettings, CookieSettings, GoogleOAuthSettings, SessionSettings, URLSettings
from belgie.auth.providers.google import GoogleOAuthProvider


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(
        secret="test-secret-key",  # noqa: S106
        base_url="http://localhost:8000",
        session=SessionSettings(
            cookie_name="belgie_session",
            max_age=3600,
            update_age=900,
        ),
        cookie=CookieSettings(
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
    assert auth.google_provider is not None
    assert auth.router is not None


def test_auth_session_manager_configuration(auth: Auth) -> None:
    assert auth.session_manager.max_age == 3600
    assert auth.session_manager.update_age == 900


def test_auth_google_provider_configuration(auth: Auth) -> None:
    assert auth.google_provider.client_id == "test-client-id"
    assert auth.google_provider.client_secret == "test-client-secret"  # noqa: S105
    assert auth.google_provider.redirect_uri == "http://localhost:8000/auth/callback/google"
    assert auth.google_provider.scopes == ["openid", "email", "profile"]


def test_auth_router_created(auth: Auth) -> None:
    assert auth.router.prefix == "/auth"
    assert "auth" in auth.router.tags


@pytest.mark.asyncio
async def test_get_google_signin_url(auth: Auth, db_session: AsyncSession) -> None:
    url = await auth.get_google_signin_url(db_session)

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-client-id" in url
    assert "state=" in url


@pytest.mark.asyncio
async def test_get_google_signin_url_creates_oauth_state(auth: Auth, db_session: AsyncSession) -> None:
    url = await auth.get_google_signin_url(db_session)

    state_param = next(param.split("=")[1] for param in url.split("?")[1].split("&") if param.startswith("state="))

    oauth_state = await auth.adapter.get_oauth_state(db_session, state_param)
    assert oauth_state is not None
    assert oauth_state.state == state_param


@pytest.mark.asyncio
@respx.mock
async def test_handle_google_callback_new_user(auth: Auth, db_session: AsyncSession) -> None:
    state_token = "test-state-123"  # noqa: S105
    await auth.adapter.create_oauth_state(
        db_session,
        state=state_token,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None),
    )

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
        "refresh_token": "test-refresh-token",
    }

    mock_user_info = {
        "id": "google-123",
        "email": "newuser@example.com",
        "verified_email": True,
        "name": "New User",
        "picture": "https://example.com/photo.jpg",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    session, user = await auth.handle_google_callback(db_session, code="test-code", state=state_token)

    assert user.email == "newuser@example.com"
    assert user.name == "New User"
    assert session.user_id == user.id

    account = await auth.adapter.get_account_by_user_and_provider(db_session, user.id, "google")
    assert account is not None
    assert account.provider == "google"
    assert account.provider_account_id == "google-123"


@pytest.mark.asyncio
@respx.mock
async def test_handle_google_callback_existing_user(auth: Auth, db_session: AsyncSession) -> None:
    existing_user = await auth.adapter.create_user(db_session, email="existing@example.com")

    state_token = "test-state-456"  # noqa: S105
    await auth.adapter.create_oauth_state(
        db_session,
        state=state_token,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None),
    )

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    mock_user_info = {
        "id": "google-456",
        "email": "existing@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    _session, user = await auth.handle_google_callback(db_session, code="test-code", state=state_token)

    assert user.id == existing_user.id
    assert user.email == "existing@example.com"


@pytest.mark.asyncio
async def test_handle_google_callback_invalid_state(auth: Auth, db_session: AsyncSession) -> None:
    with pytest.raises(InvalidStateError, match="invalid oauth state"):
        await auth.handle_google_callback(db_session, code="test-code", state="invalid-state")


@pytest.mark.asyncio
@respx.mock
async def test_handle_google_callback_token_exchange_error(auth: Auth, db_session: AsyncSession) -> None:
    state_token = "test-state-error"  # noqa: S105
    await auth.adapter.create_oauth_state(
        db_session,
        state=state_token,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None),
    )

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(OAuthError, match="failed to exchange code for tokens"):
        await auth.handle_google_callback(db_session, code="invalid-code", state=state_token)


@pytest.mark.asyncio
@respx.mock
async def test_handle_google_callback_user_info_error(auth: Auth, db_session: AsyncSession) -> None:
    state_token = "test-state-userinfo-error"  # noqa: S105
    await auth.adapter.create_oauth_state(
        db_session,
        state=state_token,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None),
    )

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(401, json={"error": "invalid_token"}))

    with pytest.raises(OAuthError, match="failed to get user info"):
        await auth.handle_google_callback(db_session, code="test-code", state=state_token)


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
    request.cookies = {auth.settings.session.cookie_name: str(session.id)}

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
    request.cookies = {auth.settings.session.cookie_name: str(uuid4())}

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
    request.cookies = {auth.settings.session.cookie_name: str(expired_session.id)}

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
    request.cookies = {auth.settings.session.cookie_name: str(session.id)}

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
    request.cookies = {auth.settings.session.cookie_name: str(session.id)}

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
    request.cookies = {auth.settings.session.cookie_name: str(session.id)}

    security_scopes = SecurityScopes(scopes=["admin"])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_session_dependency_valid(auth: Auth, db_session: AsyncSession) -> None:
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    session = await auth.session_manager.create_session(db_session, user_id=user.id)

    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.session.cookie_name: str(session.id)}

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
    request.cookies = {auth.settings.session.cookie_name: str(uuid4())}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_session_dependency_invalid_uuid_format(auth: Auth, db_session: AsyncSession) -> None:
    request = MagicMock(spec=Request)
    request.cookies = {auth.settings.session.cookie_name: "not-a-uuid"}

    with pytest.raises(HTTPException) as exc_info:
        await auth.session(request, db_session)

    assert exc_info.value.status_code == 401  # type: ignore[attr-defined]
