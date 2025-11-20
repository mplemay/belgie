"""Integration tests for scope-based authorization.

Tests the end-to-end scope validation flow using the Auth class with various
user scope configurations and Security scope requirements.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request
from fastapi.security import SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession

from __tests__.auth.fixtures.models import Account, OAuthState, Session, User
from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.core.auth import Auth
from belgie.auth.core.settings import AuthSettings, CookieSettings, GoogleOAuthSettings, SessionSettings, URLSettings


class AppScope(StrEnum):
    """Example application scopes for testing."""

    READ = "resource:read"
    WRITE = "resource:write"
    DELETE = "resource:delete"
    ADMIN = "admin"


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(
        secret="test-secret-key",  # noqa: S106
        base_url="http://localhost:8000",
        session=SessionSettings(
            cookie_name="test_session",
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
def adapter() -> AlchemyAdapter:
    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )


@pytest.fixture
def auth(auth_settings: AuthSettings, adapter: AlchemyAdapter, db_session: AsyncSession) -> Auth:
    async def get_db() -> AsyncSession:
        return db_session

    return Auth(settings=auth_settings, adapter=adapter, db_dependency=get_db)


@pytest.mark.asyncio
async def test_user_with_valid_single_scope(auth: Auth, db_session: AsyncSession, auth_settings: AuthSettings) -> None:
    """Test that a user with the required scope can access the resource."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = [AppScope.READ, AppScope.WRITE]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # User has READ scope, should succeed
    security_scopes = SecurityScopes(scopes=[AppScope.READ])
    retrieved_user = await auth.user(security_scopes, request, db_session)

    assert retrieved_user.id == user.id
    assert retrieved_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_user_without_required_scope(auth: Auth, db_session: AsyncSession, auth_settings: AuthSettings) -> None:
    """Test that a user without the required scope is denied access."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = [AppScope.READ]  # Missing ADMIN
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # User lacks ADMIN scope, should fail
    security_scopes = SecurityScopes(scopes=[AppScope.ADMIN])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    assert "insufficient scopes" in str(exc_info.value.detail)  # type: ignore[attr-defined]
    assert AppScope.ADMIN in str(exc_info.value.detail)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_with_all_required_scopes(auth: Auth, db_session: AsyncSession, auth_settings: AuthSettings) -> None:
    """Test that a user with all required scopes can access the resource."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = [AppScope.READ, AppScope.WRITE, AppScope.DELETE]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # User has both READ and WRITE scopes, should succeed
    security_scopes = SecurityScopes(scopes=[AppScope.READ, AppScope.WRITE])
    retrieved_user = await auth.user(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_user_missing_one_of_multiple_required_scopes(
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that a user missing one of multiple required scopes is denied access."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = [AppScope.READ]  # Missing WRITE
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # User has READ but not WRITE, should fail
    security_scopes = SecurityScopes(scopes=[AppScope.READ, AppScope.WRITE])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    assert "insufficient scopes" in str(exc_info.value.detail)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_with_empty_scopes_list(auth: Auth, db_session: AsyncSession, auth_settings: AuthSettings) -> None:
    """Test that a user with no scopes is denied access to scope-protected resources."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = []
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    security_scopes = SecurityScopes(scopes=[AppScope.READ])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_with_no_scope_requirements(
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that authenticated users can access resources without scope requirements."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = []  # No scopes
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # No scope requirements, should succeed even with no scopes
    security_scopes = SecurityScopes()
    retrieved_user = await auth.user(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_strenum_scopes_work_as_strings(
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that StrEnum scopes work seamlessly with string scope values."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    # Store as string values (how they're stored in DB)
    user.scopes = ["resource:read", "resource:write"]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # Use StrEnum scopes in Security - they work because StrEnum members are strings
    security_scopes = SecurityScopes(scopes=[AppScope.READ, AppScope.WRITE])
    retrieved_user = await auth.user(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_mixed_strenum_and_string_scopes(
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that StrEnum and plain string scopes can be mixed."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    # Mix of StrEnum value and plain string
    user.scopes = [AppScope.READ.value, "resource:write", AppScope.ADMIN.value]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # Mix of StrEnum and string in requirements
    security_scopes = SecurityScopes(scopes=[AppScope.READ, "resource:write"])
    retrieved_user = await auth.user(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_multiple_users_with_different_scopes(
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that different users with different scopes have appropriate access."""
    # Create admin user
    admin_user = await auth.adapter.create_user(db_session, email="admin@example.com")
    admin_user.scopes = [AppScope.ADMIN, AppScope.READ, AppScope.WRITE]
    await db_session.commit()

    admin_session = await auth.adapter.create_session(
        db_session,
        user_id=admin_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    # Create read-only user
    readonly_user = await auth.adapter.create_user(db_session, email="readonly@example.com")
    readonly_user.scopes = [AppScope.READ]
    await db_session.commit()

    readonly_session = await auth.adapter.create_session(
        db_session,
        user_id=readonly_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    # Admin can access ADMIN scope
    admin_request = MagicMock(spec=Request)
    admin_request.cookies = {auth_settings.session.cookie_name: str(admin_session.id)}

    admin_security = SecurityScopes(scopes=[AppScope.ADMIN])
    retrieved_admin = await auth.user(admin_security, admin_request, db_session)
    assert retrieved_admin.id == admin_user.id

    # Read-only user cannot access ADMIN scope
    readonly_request = MagicMock(spec=Request)
    readonly_request.cookies = {auth_settings.session.cookie_name: str(readonly_session.id)}

    readonly_security = SecurityScopes(scopes=[AppScope.ADMIN])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(readonly_security, readonly_request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_error_message_includes_required_scopes(
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that error messages include the required scopes for debugging."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = []
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    # Test that error includes all required scopes
    security_scopes = SecurityScopes(scopes=[AppScope.READ, AppScope.WRITE, AppScope.ADMIN])

    with pytest.raises(HTTPException) as exc_info:
        await auth.user(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    detail = str(exc_info.value.detail)  # type: ignore[attr-defined]
    assert "insufficient scopes" in detail
    # All required scopes should be in the error message
    assert AppScope.READ in detail or "resource:read" in detail
    assert AppScope.WRITE in detail or "resource:write" in detail
    assert AppScope.ADMIN in detail or "admin" in detail
