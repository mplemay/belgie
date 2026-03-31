"""Integration tests for scope-based authorization.

Tests the end-to-end scope validation flow using the Belgie class with various
user scope configurations and Security scope requirements.
"""

from collections.abc import AsyncGenerator, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from belgie_core.core.belgie import Belgie
from belgie_core.core.settings import BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie_proto.core.individual import IndividualProtocol
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from belgie_alchemy.__tests__.fixtures.core.models import Account, Customer, Individual, OAuthState, Session
from belgie_alchemy.core import BelgieAdapter


class AppScope(StrEnum):
    """Example application scopes for testing."""

    READ = "resource:read"
    WRITE = "resource:write"
    DELETE = "resource:delete"
    ADMIN = "admin"


# Type alias for the factory fixture
CreateUserWithSession = Callable[[str, list[AppScope] | None], Coroutine[None, None, str]]


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
            name="test_session",
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
def database(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with db_session_factory() as session:
            yield session

    return get_db


@pytest_asyncio.fixture
async def adapter():
    adapter = BelgieAdapter(
        customer=Customer,
        individual=Individual,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )
    yield adapter


@pytest.fixture
def auth(
    auth_settings: BelgieSettings,
    adapter: BelgieAdapter,
    database: Callable[[], AsyncGenerator[AsyncSession, None]],
    db_session: AsyncSession,
) -> Belgie:
    _ = db_session
    return Belgie(settings=auth_settings, adapter=adapter, database=database)


@pytest.fixture
def app(auth: Belgie, db_session: AsyncSession) -> FastAPI:  # noqa: C901
    """Create FastAPI app with auth router and scope-protected endpoints."""
    from typing import Annotated  # noqa: PLC0415

    from fastapi import Security  # noqa: PLC0415

    app = FastAPI()
    app.include_router(auth.router)

    # Override database dependency to use test db_session
    async def get_test_db() -> AsyncSession:
        return db_session

    # Create Security dependencies with scopes that delegate to auth.user
    # These avoid Pydantic validation issues by wrapping the auth.user call
    async def get_individual_with_read_scope(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),
    ) -> IndividualProtocol:
        # Merge the READ scope with any parent scopes
        all_scopes = list(set(security_scopes.scopes) | {AppScope.READ})
        security_scopes.scopes = all_scopes
        return await auth.individual(security_scopes, request, db)

    async def get_individual_with_write_scope(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),
    ) -> IndividualProtocol:
        all_scopes = list(set(security_scopes.scopes) | {AppScope.WRITE})
        security_scopes.scopes = all_scopes
        return await auth.individual(security_scopes, request, db)

    async def get_individual_with_admin_scope(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),
    ) -> IndividualProtocol:
        all_scopes = list(set(security_scopes.scopes) | {AppScope.ADMIN})
        security_scopes.scopes = all_scopes
        return await auth.individual(security_scopes, request, db)

    async def get_authenticated_individual(
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession = Depends(get_test_db),
    ) -> IndividualProtocol:
        return await auth.individual(security_scopes, request, db)

    # Type aliases for Security dependencies
    ReadIndividual = Annotated[  # noqa: N806
        IndividualProtocol,
        Security(get_individual_with_read_scope, scopes=[AppScope.READ]),
    ]
    WriteIndividual = Annotated[  # noqa: N806
        IndividualProtocol,
        Security(get_individual_with_write_scope, scopes=[AppScope.WRITE]),
    ]
    AdminIndividual = Annotated[  # noqa: N806
        IndividualProtocol,
        Security(get_individual_with_admin_scope, scopes=[AppScope.ADMIN]),
    ]
    ReadWriteIndividual = Annotated[  # noqa: N806
        IndividualProtocol,
        Security(get_individual_with_read_scope, scopes=[AppScope.READ, AppScope.WRITE]),
    ]
    AuthenticatedIndividual = Annotated[IndividualProtocol, Depends(get_authenticated_individual)]  # noqa: N806

    # Add test endpoints using Security with scopes
    @app.get("/api/read")
    async def read_resource(individual: ReadIndividual) -> dict:
        return {"message": "read access granted", "individual_email": individual.email}

    @app.get("/api/write")
    async def write_resource(individual: WriteIndividual) -> dict:
        return {"message": "write access granted", "individual_email": individual.email}

    @app.get("/api/admin")
    async def admin_resource(individual: AdminIndividual) -> dict:
        return {"message": "admin access granted", "individual_email": individual.email}

    @app.get("/api/read-write")
    async def read_write_resource(individual: ReadWriteIndividual) -> dict:
        return {"message": "read-write access granted", "individual_email": individual.email}

    @app.get("/api/public")
    async def public_resource(individual: AuthenticatedIndividual) -> dict:
        return {"message": "public access granted", "individual_email": individual.email}

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client for making HTTP requests."""
    return TestClient(app)


@pytest_asyncio.fixture
async def create_individual_with_session(auth: Belgie, db_session: AsyncSession) -> CreateUserWithSession:
    """Factory fixture to create individuals with scopes and sessions."""

    async def _create(email: str, scopes: list[AppScope] | None = None) -> str:
        user = await auth.adapter.create_individual(db_session, email=email)
        user.scopes = scopes
        await db_session.commit()

        session = await auth.adapter.create_session(
            db_session,
            individual_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        return str(session.id)

    return _create


@pytest.mark.asyncio
async def test_individual_with_valid_single_scope(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that a user with the required scope can access the resource."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    user.scopes = [AppScope.READ, AppScope.WRITE]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    # Individual has READ scope, should succeed
    security_scopes = SecurityScopes(scopes=[AppScope.READ])
    retrieved_user = await auth.individual(security_scopes, request, db_session)

    assert retrieved_user.id == user.id
    assert retrieved_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_individual_without_required_scope(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that a user without the required scope is denied access."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    user.scopes = [AppScope.READ]  # Missing ADMIN
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    # Individual lacks ADMIN scope, should fail
    security_scopes = SecurityScopes(scopes=[AppScope.ADMIN])

    with pytest.raises(HTTPException) as exc_info:
        await auth.individual(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    assert exc_info.value.detail == "Insufficient permissions"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_individual_with_all_required_scopes(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that a user with all required scopes can access the resource."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    user.scopes = [AppScope.READ, AppScope.WRITE, AppScope.DELETE]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    # Individual has both READ and WRITE scopes, should succeed
    security_scopes = SecurityScopes(scopes=[AppScope.READ, AppScope.WRITE])
    retrieved_user = await auth.individual(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_individual_missing_one_of_multiple_required_scopes(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that a user missing one of multiple required scopes is denied access."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    user.scopes = [AppScope.READ]  # Missing WRITE
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    # Individual has READ but not WRITE, should fail
    security_scopes = SecurityScopes(scopes=[AppScope.READ, AppScope.WRITE])

    with pytest.raises(HTTPException) as exc_info:
        await auth.individual(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    assert exc_info.value.detail == "Insufficient permissions"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_individual_with_empty_scopes_list(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that a user with no scopes is denied access to scope-protected resources."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    user.scopes = []
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes(scopes=[AppScope.READ])

    with pytest.raises(HTTPException) as exc_info:
        await auth.individual(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_individual_with_default_empty_scopes(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that a new user with default empty scopes is denied access to scope-protected resources."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    assert user.scopes == []
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes(scopes=[AppScope.READ])

    with pytest.raises(HTTPException) as exc_info:
        await auth.individual(security_scopes, request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_individual_with_default_empty_scopes_no_requirements(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that a new user with default empty scopes can access endpoints with no scope requirements."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    assert user.scopes == []
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    security_scopes = SecurityScopes(scopes=[])

    result: IndividualProtocol = await auth.individual(security_scopes, request, db_session)

    assert result.id == user.id
    assert result.scopes == []


@pytest.mark.asyncio
async def test_individual_with_no_scope_requirements(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that authenticated individuals can access resources without scope requirements."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    user.scopes = []  # No scopes
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    # No scope requirements, should succeed even with no scopes
    security_scopes = SecurityScopes()
    retrieved_user = await auth.individual(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_strenum_scopes_work_as_strings(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that StrEnum scopes work seamlessly with string scope values."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    # Store as string values (how they're stored in DB)
    user.scopes = ["resource:read", "resource:write"]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    # Use StrEnum scopes in Security - they work because StrEnum members are strings
    security_scopes = SecurityScopes(scopes=[AppScope.READ, AppScope.WRITE])
    retrieved_user = await auth.individual(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_mixed_strenum_and_string_scopes(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that StrEnum and plain string scopes can be mixed."""
    user = await auth.adapter.create_individual(db_session, email="test@example.com")
    # Mix of StrEnum value and plain string
    user.scopes = [AppScope.READ.value, "resource:write", AppScope.ADMIN.value]
    await db_session.commit()

    session = await auth.adapter.create_session(
        db_session,
        individual_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    request = MagicMock(spec=Request)
    request.cookies = {auth_settings.cookie.name: str(session.id)}

    # Mix of StrEnum and string in requirements
    security_scopes = SecurityScopes(scopes=[AppScope.READ, "resource:write"])
    retrieved_user = await auth.individual(security_scopes, request, db_session)

    assert retrieved_user.id == user.id


@pytest.mark.asyncio
async def test_multiple_individuals_with_different_scopes(
    auth: Belgie,
    db_session: AsyncSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that different individuals with different scopes have appropriate access."""
    # Create admin user
    admin_user = await auth.adapter.create_individual(db_session, email="admin@example.com")
    admin_user.scopes = [AppScope.ADMIN, AppScope.READ, AppScope.WRITE]
    await db_session.commit()

    admin_session = await auth.adapter.create_session(
        db_session,
        individual_id=admin_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    # Create read-only user
    readonly_user = await auth.adapter.create_individual(db_session, email="readonly@example.com")
    readonly_user.scopes = [AppScope.READ]
    await db_session.commit()

    readonly_session = await auth.adapter.create_session(
        db_session,
        individual_id=readonly_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await db_session.commit()

    # Admin can access ADMIN scope
    admin_request = MagicMock(spec=Request)
    admin_request.cookies = {auth_settings.cookie.name: str(admin_session.id)}

    admin_security = SecurityScopes(scopes=[AppScope.ADMIN])
    retrieved_admin = await auth.individual(admin_security, admin_request, db_session)
    assert retrieved_admin.id == admin_user.id

    # Read-only user cannot access ADMIN scope
    readonly_request = MagicMock(spec=Request)
    readonly_request.cookies = {auth_settings.cookie.name: str(readonly_session.id)}

    readonly_security = SecurityScopes(scopes=[AppScope.ADMIN])

    with pytest.raises(HTTPException) as exc_info:
        await auth.individual(readonly_security, readonly_request, db_session)

    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


# HTTP Endpoint Integration Tests


@pytest.mark.asyncio
async def test_http_endpoint_with_valid_scope(
    client: TestClient,
    create_individual_with_session: CreateUserWithSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that HTTP request with valid scope can access protected endpoint."""
    session_id = await create_individual_with_session("reader@example.com", [AppScope.READ, AppScope.WRITE])

    client.cookies.set(auth_settings.cookie.name, session_id)
    response = client.get("/api/read")

    assert response.status_code == 200
    assert response.json()["message"] == "read access granted"
    assert response.json()["individual_email"] == "reader@example.com"


@pytest.mark.asyncio
async def test_http_endpoint_without_required_scope(
    client: TestClient,
    create_individual_with_session: CreateUserWithSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that HTTP request without required scope is denied access."""
    session_id = await create_individual_with_session("limited@example.com", [AppScope.READ])

    client.cookies.set(auth_settings.cookie.name, session_id)
    response = client.get("/api/admin")

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"


@pytest.mark.asyncio
async def test_http_endpoint_with_multiple_required_scopes(
    client: TestClient,
    create_individual_with_session: CreateUserWithSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test HTTP endpoint requiring multiple scopes."""
    session_id = await create_individual_with_session(
        "fullaccess@example.com",
        [AppScope.READ, AppScope.WRITE, AppScope.DELETE],
    )

    client.cookies.set(auth_settings.cookie.name, session_id)
    response = client.get("/api/read-write")

    assert response.status_code == 200
    assert response.json()["message"] == "read-write access granted"


@pytest.mark.asyncio
async def test_http_endpoint_missing_one_of_multiple_scopes(
    client: TestClient,
    create_individual_with_session: CreateUserWithSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that missing one of multiple required scopes denies access."""
    session_id = await create_individual_with_session("readonly@example.com", [AppScope.READ])

    client.cookies.set(auth_settings.cookie.name, session_id)
    response = client.get("/api/read-write")

    assert response.status_code == 403


def test_http_endpoint_without_authentication(client: TestClient) -> None:
    """Test that unauthenticated requests are denied."""
    response = client.get("/api/read")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_http_public_endpoint_with_authentication(
    client: TestClient,
    create_individual_with_session: CreateUserWithSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test public endpoint (no scope requirements) with authenticated user."""
    session_id = await create_individual_with_session("anyuser@example.com", None)

    client.cookies.set(auth_settings.cookie.name, session_id)
    response = client.get("/api/public")

    assert response.status_code == 200
    assert response.json()["message"] == "public access granted"


@pytest.mark.asyncio
async def test_http_different_individuals_different_access(
    client: TestClient,
    create_individual_with_session: CreateUserWithSession,
    auth_settings: BelgieSettings,
) -> None:
    """Test that different individuals have appropriate access based on their scopes."""
    admin_session_id = await create_individual_with_session(
        "admin@example.com",
        [AppScope.ADMIN, AppScope.READ, AppScope.WRITE],
    )
    regular_session_id = await create_individual_with_session("regular@example.com", [AppScope.READ])

    # Admin can access admin endpoint
    client.cookies.set(auth_settings.cookie.name, admin_session_id)
    admin_response = client.get("/api/admin")
    assert admin_response.status_code == 200
    assert admin_response.json()["individual_email"] == "admin@example.com"

    # Regular user cannot access admin endpoint
    client.cookies.set(auth_settings.cookie.name, regular_session_id)
    regular_response = client.get("/api/admin")
    assert regular_response.status_code == 403

    # Regular user can access read endpoint
    regular_read_response = client.get("/api/read")
    assert regular_read_response.status_code == 200
    assert regular_read_response.json()["individual_email"] == "regular@example.com"
