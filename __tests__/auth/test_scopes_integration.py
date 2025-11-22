"""Integration tests for scope-based authorization.

Tests the end-to-end scope validation flow using the Auth class with various
user scope configurations and Security scope requirements.
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
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


# Type alias for the factory fixture
CreateUserWithSession = Callable[[str, list[AppScope] | None], Coroutine[None, None, str]]


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


@pytest.fixture
def app(auth: Auth, db_session: AsyncSession) -> FastAPI:  # noqa: C901
    """Create FastAPI app with auth router and scope-protected endpoints."""
    from typing import Annotated  # noqa: PLC0415

    from fastapi import Security  # noqa: PLC0415

    app = FastAPI()
    app.include_router(auth.router)

    # Override database dependency to use test db_session
    async def get_test_db() -> AsyncSession:
        return db_session

    if db_func := auth.adapter.get_db():
        app.dependency_overrides[db_func] = get_test_db

    # Create Security dependencies with scopes that delegate to auth.user
    # These avoid Pydantic validation issues by wrapping the auth.user call
    async def get_user_with_read_scope(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        # Merge the READ scope with any parent scopes
        all_scopes = list(set(security_scopes.scopes) | {AppScope.READ})
        security_scopes.scopes = all_scopes
        return await auth.user(security_scopes, request, db)

    async def get_user_with_write_scope(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        all_scopes = list(set(security_scopes.scopes) | {AppScope.WRITE})
        security_scopes.scopes = all_scopes
        return await auth.user(security_scopes, request, db)

    async def get_user_with_admin_scope(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        all_scopes = list(set(security_scopes.scopes) | {AppScope.ADMIN})
        security_scopes.scopes = all_scopes
        return await auth.user(security_scopes, request, db)

    async def get_authenticated_user(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),  # noqa: B008
    ) -> UserProtocol:
        return await auth.user(security_scopes, request, db)

    # Type aliases for Security dependencies
    ReadUser = Annotated[UserProtocol, Security(get_user_with_read_scope, scopes=[AppScope.READ])]  # noqa: N806
    WriteUser = Annotated[UserProtocol, Security(get_user_with_write_scope, scopes=[AppScope.WRITE])]  # noqa: N806
    AdminUser = Annotated[UserProtocol, Security(get_user_with_admin_scope, scopes=[AppScope.ADMIN])]  # noqa: N806
    ReadWriteUser = Annotated[  # noqa: N806
        UserProtocol,
        Security(get_user_with_read_scope, scopes=[AppScope.READ, AppScope.WRITE]),
    ]
    AuthenticatedUser = Annotated[UserProtocol, Depends(get_authenticated_user)]  # noqa: N806

    # Add test endpoints using Security with scopes
    @app.get("/api/read")
    async def read_resource(user: ReadUser) -> dict:
        return {"message": "read access granted", "user_email": user.email}

    @app.get("/api/write")
    async def write_resource(user: WriteUser) -> dict:
        return {"message": "write access granted", "user_email": user.email}

    @app.get("/api/admin")
    async def admin_resource(user: AdminUser) -> dict:
        return {"message": "admin access granted", "user_email": user.email}

    @app.get("/api/read-write")
    async def read_write_resource(user: ReadWriteUser) -> dict:
        return {"message": "read-write access granted", "user_email": user.email}

    @app.get("/api/public")
    async def public_resource(user: AuthenticatedUser) -> dict:
        return {"message": "public access granted", "user_email": user.email}

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client for making HTTP requests."""
    return TestClient(app)


@pytest_asyncio.fixture
async def create_user_with_session(auth: Auth, db_session: AsyncSession) -> CreateUserWithSession:
    """Factory fixture to create users with scopes and sessions."""

    async def _create(email: str, scopes: list[AppScope] | None = None) -> str:
        user = await auth.adapter.create_user(db_session, email=email)
        user.scopes = scopes
        await db_session.commit()

        session = await auth.adapter.create_session(
            db_session,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        return str(session.id)

    return _create


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
    assert exc_info.value.detail == "Insufficient permissions"  # type: ignore[attr-defined]


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
    assert exc_info.value.detail == "Insufficient permissions"  # type: ignore[attr-defined]


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
async def test_user_with_none_scopes(auth: Auth, db_session: AsyncSession, auth_settings: AuthSettings) -> None:
    """Test that a user with None scopes is denied access to scope-protected resources.

    None scopes should behave identically to empty scopes list.
    """
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = None
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
async def test_user_with_none_scopes_no_requirements(
    auth: Auth,
    db_session: AsyncSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that a user with None scopes can access endpoints with no scope requirements."""
    user = await auth.adapter.create_user(db_session, email="test@example.com")
    user.scopes = None
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.session.cookie_name: str(session.id)}

    security_scopes = SecurityScopes(scopes=[])

    result: UserProtocol = await auth.user(security_scopes, request, db_session)

    assert result.id == user.id
    assert result.scopes is None


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


# HTTP Endpoint Integration Tests


@pytest.mark.asyncio
async def test_http_endpoint_with_valid_scope(
    client: TestClient,
    create_user_with_session: CreateUserWithSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that HTTP request with valid scope can access protected endpoint."""
    session_id = await create_user_with_session("reader@example.com", [AppScope.READ, AppScope.WRITE])

    response = client.get("/api/read", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 200
    assert response.json()["message"] == "read access granted"
    assert response.json()["user_email"] == "reader@example.com"


@pytest.mark.asyncio
async def test_http_endpoint_without_required_scope(
    client: TestClient,
    create_user_with_session: CreateUserWithSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that HTTP request without required scope is denied access."""
    session_id = await create_user_with_session("limited@example.com", [AppScope.READ])

    response = client.get("/api/admin", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"


@pytest.mark.asyncio
async def test_http_endpoint_with_multiple_required_scopes(
    client: TestClient,
    create_user_with_session: CreateUserWithSession,
    auth_settings: AuthSettings,
) -> None:
    """Test HTTP endpoint requiring multiple scopes."""
    session_id = await create_user_with_session(
        "fullaccess@example.com",
        [AppScope.READ, AppScope.WRITE, AppScope.DELETE],
    )

    response = client.get("/api/read-write", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 200
    assert response.json()["message"] == "read-write access granted"


@pytest.mark.asyncio
async def test_http_endpoint_missing_one_of_multiple_scopes(
    client: TestClient,
    create_user_with_session: CreateUserWithSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that missing one of multiple required scopes denies access."""
    session_id = await create_user_with_session("readonly@example.com", [AppScope.READ])

    response = client.get("/api/read-write", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 403


def test_http_endpoint_without_authentication(client: TestClient) -> None:
    """Test that unauthenticated requests are denied."""
    response = client.get("/api/read")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_http_public_endpoint_with_authentication(
    client: TestClient,
    create_user_with_session: CreateUserWithSession,
    auth_settings: AuthSettings,
) -> None:
    """Test public endpoint (no scope requirements) with authenticated user."""
    session_id = await create_user_with_session("anyuser@example.com", None)

    response = client.get("/api/public", cookies={auth_settings.session.cookie_name: session_id})

    assert response.status_code == 200
    assert response.json()["message"] == "public access granted"


@pytest.mark.asyncio
async def test_http_different_users_different_access(
    client: TestClient,
    create_user_with_session: CreateUserWithSession,
    auth_settings: AuthSettings,
) -> None:
    """Test that different users have appropriate access based on their scopes."""
    admin_session_id = await create_user_with_session(
        "admin@example.com",
        [AppScope.ADMIN, AppScope.READ, AppScope.WRITE],
    )
    regular_session_id = await create_user_with_session("regular@example.com", [AppScope.READ])

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
