"""Integration tests for scope-based authorization.

Tests the end-to-end scope validation flow using the Auth class with various
user scope configurations and Security scope requirements.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from __tests__.auth.fixtures.models import Account, OAuthState, Session, User
from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.core.auth import Auth
from belgie.auth.core.settings import AuthSettings, CookieSettings, GoogleOAuthSettings, SessionSettings, URLSettings
from belgie.auth.protocols.models import UserProtocol


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


@pytest.fixture
def app(auth: Auth, db_session: AsyncSession) -> FastAPI:  # noqa: C901
    """Create FastAPI app with auth router and scope-protected endpoints."""
    app = FastAPI()
    app.include_router(auth.router)

    # Override database dependency to use test db_session
    async def get_test_db() -> AsyncSession:
        return db_session

    # Create custom dependencies for each scope requirement
    async def require_read(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        security_scopes.scopes = [AppScope.READ]
        return await auth.user(security_scopes, request, db)

    async def require_write(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        security_scopes.scopes = [AppScope.WRITE]
        return await auth.user(security_scopes, request, db)

    async def require_admin(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        security_scopes.scopes = [AppScope.ADMIN]
        return await auth.user(security_scopes, request, db)

    async def require_read_write(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        security_scopes.scopes = [AppScope.READ, AppScope.WRITE]
        return await auth.user(security_scopes, request, db)

    async def require_auth(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        return await auth.user(security_scopes, request, db)

    # Add test endpoints with different scope requirements
    @app.get("/api/read")
    async def read_resource(user: UserProtocol = Depends(require_read)) -> dict:  # noqa: B008, FAST002
        return {"message": "read access granted", "user_email": user.email}

    @app.get("/api/write")
    async def write_resource(user: UserProtocol = Depends(require_write)) -> dict:  # noqa: B008, FAST002
        return {"message": "write access granted", "user_email": user.email}

    @app.get("/api/admin")
    async def admin_resource(user: UserProtocol = Depends(require_admin)) -> dict:  # noqa: B008, FAST002
        return {"message": "admin access granted", "user_email": user.email}

    @app.get("/api/read-write")
    async def read_write_resource(user: UserProtocol = Depends(require_read_write)) -> dict:  # noqa: B008, FAST002
        return {"message": "read-write access granted", "user_email": user.email}

    @app.get("/api/public")
    async def public_resource(user: UserProtocol = Depends(require_auth)) -> dict:  # noqa: B008, FAST002
        return {"message": "public access granted", "user_email": user.email}

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client for making HTTP requests."""
    return TestClient(app)


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


# HTTP Endpoint Integration Tests


def test_http_endpoint_with_valid_scope(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that HTTP request with valid scope can access protected endpoint."""
    import asyncio  # noqa: PLC0415

    async def setup_user_and_session() -> str:
        user = await auth.adapter.create_user(db_session, email="reader@example.com")
        user.scopes = [AppScope.READ, AppScope.WRITE]
        await db_session.commit()

        session = await auth.adapter.create_session(
            db_session,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        return str(session.id)

    session_id = asyncio.run(setup_user_and_session())

    response = client.get("/api/read", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 200
    assert response.json()["message"] == "read access granted"
    assert response.json()["user_email"] == "reader@example.com"


def test_http_endpoint_without_required_scope(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that HTTP request without required scope is denied access."""
    import asyncio  # noqa: PLC0415

    async def setup_user_and_session() -> str:
        user = await auth.adapter.create_user(db_session, email="limited@example.com")
        user.scopes = [AppScope.READ]  # Missing ADMIN
        await db_session.commit()

        session = await auth.adapter.create_session(
            db_session,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        return str(session.id)

    session_id = asyncio.run(setup_user_and_session())

    response = client.get("/api/admin", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 403
    assert "insufficient scopes" in response.json()["detail"]


def test_http_endpoint_with_multiple_required_scopes(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test HTTP endpoint requiring multiple scopes."""
    import asyncio  # noqa: PLC0415

    async def setup_user_and_session() -> str:
        user = await auth.adapter.create_user(db_session, email="fullaccess@example.com")
        user.scopes = [AppScope.READ, AppScope.WRITE, AppScope.DELETE]
        await db_session.commit()

        session = await auth.adapter.create_session(
            db_session,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        return str(session.id)

    session_id = asyncio.run(setup_user_and_session())

    response = client.get("/api/read-write", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 200
    assert response.json()["message"] == "read-write access granted"


def test_http_endpoint_missing_one_of_multiple_scopes(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that missing one of multiple required scopes denies access."""
    import asyncio  # noqa: PLC0415

    async def setup_user_and_session() -> str:
        user = await auth.adapter.create_user(db_session, email="readonly@example.com")
        user.scopes = [AppScope.READ]  # Missing WRITE
        await db_session.commit()

        session = await auth.adapter.create_session(
            db_session,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        return str(session.id)

    session_id = asyncio.run(setup_user_and_session())

    response = client.get("/api/read-write", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 403


def test_http_endpoint_without_authentication(client: TestClient) -> None:
    """Test that unauthenticated requests are denied."""
    response = client.get("/api/read")
    assert response.status_code == 401


def test_http_public_endpoint_with_authentication(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test public endpoint (no scope requirements) with authenticated user."""
    import asyncio  # noqa: PLC0415

    async def setup_user_and_session() -> str:
        user = await auth.adapter.create_user(db_session, email="anyuser@example.com")
        user.scopes = []  # No scopes
        await db_session.commit()

        session = await auth.adapter.create_session(
            db_session,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        return str(session.id)

    session_id = asyncio.run(setup_user_and_session())

    response = client.get("/api/public", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 200
    assert response.json()["message"] == "public access granted"


def test_http_different_users_different_access(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that different users have appropriate access based on their scopes."""
    import asyncio  # noqa: PLC0415

    async def setup_users_and_sessions() -> tuple[str, str]:
        # Admin user
        admin = await auth.adapter.create_user(db_session, email="admin@example.com")
        admin.scopes = [AppScope.ADMIN, AppScope.READ, AppScope.WRITE]
        await db_session.commit()

        admin_session = await auth.adapter.create_session(
            db_session,
            user_id=admin.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()

        # Regular user
        regular = await auth.adapter.create_user(db_session, email="regular@example.com")
        regular.scopes = [AppScope.READ]
        await db_session.commit()

        regular_session = await auth.adapter.create_session(
            db_session,
            user_id=regular.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()

        return str(admin_session.id), str(regular_session.id)

    admin_session_id, regular_session_id = asyncio.run(setup_users_and_sessions())

    # Admin can access admin endpoint
    admin_response = client.get("/api/admin", cookies={auth_settings.session.cookie_name: admin_session_id})
    assert admin_response.status_code == 200
    assert admin_response.json()["user_email"] == "admin@example.com"

    # Regular user cannot access admin endpoint
    regular_response = client.get("/api/admin", cookies={auth_settings.session.cookie_name: regular_session_id})
    assert regular_response.status_code == 403

    # Regular user can access read endpoint
    regular_read_response = client.get("/api/read", cookies={auth_settings.session.cookie_name: regular_session_id})
    assert regular_read_response.status_code == 200
    assert regular_read_response.json()["user_email"] == "regular@example.com"
