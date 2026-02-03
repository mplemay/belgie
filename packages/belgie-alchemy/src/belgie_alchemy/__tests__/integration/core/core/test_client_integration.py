from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from belgie_alchemy import AlchemyAdapter
from belgie_alchemy.__tests__.fixtures.models import Account, OAuthState, Session, User
from belgie_core.core.belgie import Belgie
from belgie_core.core.client import BelgieClient
from belgie_core.core.settings import (
    BelgieSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# ==================== Fixtures ====================


@pytest.fixture
def auth_settings() -> BelgieSettings:
    """Test auth configuration with safe defaults."""
    return BelgieSettings(
        secret="test-integration-secret",
        base_url="http://testserver",
        session=SessionSettings(max_age=3600, update_age=900),
        cookie=CookieSettings(
            name="test_client_session",
            secure=False,
            http_only=True,
            same_site="lax",
        ),
        urls=URLSettings(signin_redirect="/dashboard", signout_redirect="/"),
    )


@pytest.fixture
def adapter(db_session: AsyncSession) -> AlchemyAdapter:  # noqa: ARG001
    """Adapter with test database dependency."""

    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )


@pytest.fixture
def auth(auth_settings: BelgieSettings, adapter: AlchemyAdapter, db_session: AsyncSession) -> Belgie:
    """Belgie instance (BelgieClient factory)."""

    async def get_db_override():
        yield db_session

    fake_db = SimpleNamespace(dependency=get_db_override)
    return Belgie(settings=auth_settings, adapter=adapter, providers=None, db=fake_db)


@pytest.fixture
def app(auth: Belgie) -> FastAPI:
    """FastAPI app with test endpoints using BelgieClient."""
    app = FastAPI()

    # User Authentication Endpoints
    @app.get("/me")
    async def get_current_user(
        request: Request,
        client: BelgieClient = Depends(auth),
    ):
        """Get user without scope requirements."""
        user = await client.get_user(SecurityScopes(), request)
        return {"id": str(user.id), "email": user.email, "scopes": user.scopes}

    @app.get("/me/with-read-scope")
    async def get_user_with_read(
        request: Request,
        client: BelgieClient = Depends(auth),
    ):
        """Get user with READ scope requirement."""
        user = await client.get_user(SecurityScopes(scopes=["resource:read"]), request)
        return {"email": user.email}

    @app.get("/me/with-admin-scope")
    async def get_user_with_admin(
        request: Request,
        client: BelgieClient = Depends(auth),
    ):
        """Get user with ADMIN scope requirement."""
        user = await client.get_user(SecurityScopes(scopes=["admin"]), request)
        return {"email": user.email}

    @app.get("/me/with-multiple-scopes")
    async def get_user_with_multiple(
        request: Request,
        client: BelgieClient = Depends(auth),
    ):
        """Get user with multiple scope requirements."""
        user = await client.get_user(
            SecurityScopes(scopes=["resource:read", "resource:write"]),
            request,
        )
        return {"email": user.email}

    # Session Management
    @app.get("/session/info")
    async def get_session_info(
        request: Request,
        client: BelgieClient = Depends(auth),
    ):
        """Get current session."""
        session = await client.get_session(request)
        return {
            "id": str(session.id),
            "user_id": str(session.user_id),
            "expires_at": session.expires_at.isoformat(),
        }

    # User Management
    @app.delete("/account")
    async def delete_account(
        request: Request,
        client: BelgieClient = Depends(auth),
    ):
        """Delete user account (cascade)."""
        user = await client.get_user(SecurityScopes(), request)
        success = await client.delete_user(user)
        return {"deleted": success}

    # Admin Endpoints
    @app.post("/admin/signout-user/{session_id}")
    async def admin_signout(
        session_id: UUID,
        client: BelgieClient = Depends(auth),
    ):
        """Sign out specific session."""
        success = await client.sign_out(session_id)
        return {"signed_out": success}

    @app.get("/admin/get-user-by-session/{session_id}")
    async def admin_get_user(
        session_id: UUID,
        client: BelgieClient = Depends(auth),
    ):
        """Get user by session ID."""
        user = await client.get_user_from_session(session_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"id": str(user.id), "email": user.email}

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """HTTP test client."""
    return TestClient(app)


# Helper Fixtures


@pytest_asyncio.fixture
async def create_user_helper(adapter: AlchemyAdapter, db_session: AsyncSession):
    """Factory for creating users with scopes."""

    async def _create(email: str, scopes: list[str] | None = None, name: str = "Test User") -> User:
        user = await adapter.create_user(db_session, email=email, name=name)
        if scopes is not None:
            user.scopes = scopes
            await db_session.commit()
            await db_session.refresh(user)
        return user

    return _create


@pytest_asyncio.fixture
async def create_session_helper(adapter: AlchemyAdapter, db_session: AsyncSession):
    """Factory for creating sessions with custom expiration."""

    async def _create(
        user_id: UUID,
        expires_at: datetime | None = None,
        ip_address: str = "127.0.0.1",
        user_agent: str = "Test Client",
    ) -> Session:
        if expires_at is None:
            expires_at = datetime.now(UTC) + timedelta(hours=1)

        return await adapter.create_session(
            db_session,
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    return _create


@pytest_asyncio.fixture
async def create_account_helper(adapter: AlchemyAdapter, db_session: AsyncSession):
    """Factory for creating OAuth accounts."""

    async def _create(
        user_id: UUID,
        provider: str = "google",
        provider_account_id: str | None = None,
    ) -> Account:
        if provider_account_id is None:
            provider_account_id = f"provider-{uuid4()}"

        return await adapter.create_account(
            db_session,
            user_id=user_id,
            provider=provider,
            provider_account_id=provider_account_id,
            access_token="test-token",
        )

    return _create


@pytest.fixture
def make_request_with_cookie(auth_settings: BelgieSettings):
    """Helper to set session cookie on test client."""

    def _make(client: TestClient, session_id: UUID) -> TestClient:
        client.cookies.set(auth_settings.cookie.name, str(session_id))
        return client

    return _make


# ==================== Tests ====================


class TestGetUser:
    """Tests for BelgieClient.get_user() method."""

    # Success cases

    @pytest.mark.asyncio
    async def test_get_user_success_without_scopes(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test getting authenticated user without scope requirements."""
        user = await create_user_helper("user@test.com")
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me")

        assert response.status_code == 200
        assert response.json()["email"] == "user@test.com"
        assert response.json()["id"] == str(user.id)

    @pytest.mark.asyncio
    async def test_get_user_success_with_valid_single_scope(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test getting user when they have required scope."""
        user = await create_user_helper("reader@test.com", scopes=["resource:read", "resource:write"])
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-read-scope")

        assert response.status_code == 200
        assert response.json()["email"] == "reader@test.com"

    @pytest.mark.asyncio
    async def test_get_user_success_with_multiple_scopes(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test getting user when they have all required scopes."""
        user = await create_user_helper(
            "power@test.com",
            scopes=["resource:read", "resource:write", "admin"],
        )
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-multiple-scopes")

        assert response.status_code == 200
        assert response.json()["email"] == "power@test.com"

    @pytest.mark.asyncio
    async def test_get_user_success_with_extra_scopes(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test getting user when they have more scopes than required."""
        user = await create_user_helper(
            "extra@test.com",
            scopes=["resource:read", "resource:write", "admin", "superuser"],
        )
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-read-scope")

        assert response.status_code == 200
        assert response.json()["email"] == "extra@test.com"

    # Authentication failures

    @pytest.mark.asyncio
    async def test_get_user_no_cookie_returns_401(self, client: TestClient):
        """Test that missing cookie returns 401."""
        response = client.get("/me")

        assert response.status_code == 401
        assert response.json()["detail"] == "not authenticated"

    @pytest.mark.asyncio
    async def test_get_user_invalid_uuid_cookie_returns_401(
        self,
        client: TestClient,
        auth_settings: BelgieSettings,
    ):
        """Test that invalid UUID in cookie returns 401."""
        client.cookies.set(auth_settings.cookie.name, "not-a-valid-uuid")

        response = client.get("/me")

        assert response.status_code == 401
        assert response.json()["detail"] == "not authenticated"

    @pytest.mark.asyncio
    async def test_get_user_expired_session_returns_401(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that expired session returns 401."""
        user = await create_user_helper("expired@test.com")
        expired_time = datetime.now(UTC) - timedelta(hours=1)
        session = await create_session_helper(user.id, expires_at=expired_time)
        make_request_with_cookie(client, session.id)

        response = client.get("/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_user_session_exists_but_user_deleted_returns_401(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test that session with deleted user returns 401.

        Note: Due to CASCADE delete, when user is deleted, their sessions are also deleted.
        So this returns 'not authenticated' instead of 'user not found'.
        """
        user = await create_user_helper("deleted@test.com")
        session = await create_session_helper(user.id)

        # Delete user (cascade also deletes session)
        await adapter.delete_user(db_session, user.id)

        make_request_with_cookie(client, session.id)
        response = client.get("/me")

        assert response.status_code == 401
        assert response.json()["detail"] == "not authenticated"

    # Scope validation failures

    @pytest.mark.asyncio
    async def test_get_user_insufficient_scope_returns_403(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user without required scope gets 403."""
        user = await create_user_helper("limited@test.com", scopes=["resource:read"])
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-admin-scope")

        assert response.status_code == 403
        assert response.json()["detail"] == "Insufficient permissions"

    @pytest.mark.asyncio
    async def test_get_user_missing_one_of_multiple_scopes_returns_403(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user missing one of multiple required scopes gets 403."""
        user = await create_user_helper("partial@test.com", scopes=["resource:read"])
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-multiple-scopes")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_empty_scopes_with_requirements_returns_403(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user with empty scopes cannot access scope-protected endpoint."""
        user = await create_user_helper("noscopes@test.com", scopes=[])
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-read-scope")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_none_scopes_with_requirements_returns_403(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user with None scopes cannot access scope-protected endpoint."""
        user = await create_user_helper("nonescopes@test.com", scopes=None)
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-read-scope")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_wrong_scopes_returns_403(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user with wrong scopes gets 403."""
        user = await create_user_helper("wrong@test.com", scopes=["different:scope"])
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me/with-admin-scope")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_user_empty_scopes_without_requirements_success(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user with empty scopes can access non-protected endpoint."""
        user = await create_user_helper("noscopes@test.com", scopes=[])
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me")

        assert response.status_code == 200
        assert response.json()["email"] == "noscopes@test.com"

    @pytest.mark.asyncio
    async def test_get_user_none_scopes_without_requirements_success(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user with None scopes can access non-protected endpoint."""
        user = await create_user_helper("nonescopes@test.com", scopes=None)
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me")

        assert response.status_code == 200
        assert response.json()["email"] == "nonescopes@test.com"


class TestGetSession:
    """Tests for BelgieClient.get_session() method."""

    @pytest.mark.asyncio
    async def test_get_session_success(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test getting session information."""
        user = await create_user_helper("session@test.com")
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/session/info")

        assert response.status_code == 200
        json = response.json()
        assert json["id"] == str(session.id)
        assert json["user_id"] == str(user.id)
        assert "expires_at" in json

    @pytest.mark.asyncio
    async def test_get_session_no_cookie_returns_401(self, client: TestClient):
        """Test that missing cookie returns 401."""
        response = client.get("/session/info")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_session_invalid_uuid_returns_401(
        self,
        client: TestClient,
        auth_settings: BelgieSettings,
    ):
        """Test that invalid UUID returns 401."""
        client.cookies.set(auth_settings.cookie.name, "invalid-uuid")

        response = client.get("/session/info")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_session_expired_returns_401(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that expired session returns 401."""
        user = await create_user_helper("expired@test.com")
        expired_time = datetime.now(UTC) - timedelta(hours=1)
        session = await create_session_helper(user.id, expires_at=expired_time)
        make_request_with_cookie(client, session.id)

        response = client.get("/session/info")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_session_sliding_window_refresh(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test that session is refreshed when within update_age threshold."""
        user = await create_user_helper("refresh@test.com")

        # Create session that expires in 10 minutes (less than update_age of 15 min)
        nearly_expired = datetime.now(UTC) + timedelta(minutes=10)
        session = await create_session_helper(user.id, expires_at=nearly_expired)
        make_request_with_cookie(client, session.id)

        response = client.get("/session/info")

        assert response.status_code == 200

        # Verify session was refreshed in database
        refreshed_session = await adapter.get_session(db_session, session.id)
        assert refreshed_session is not None
        # Compare as timezone-aware datetimes
        refreshed_expires = refreshed_session.expires_at.replace(tzinfo=UTC)
        assert refreshed_expires > nearly_expired


class TestDeleteUser:
    """Tests for BelgieClient.delete_user() method."""

    @pytest.mark.asyncio
    async def test_delete_user_success(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test successful user deletion."""
        user = await create_user_helper("delete@test.com")
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.delete("/account")

        assert response.status_code == 200
        assert response.json()["deleted"] is True

        # Verify user is deleted from database
        deleted_user = await adapter.get_user_by_id(db_session, user.id)
        assert deleted_user is None

    @pytest.mark.asyncio
    async def test_delete_user_cascade_deletes_sessions(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test that deleting user also deletes their sessions."""
        user = await create_user_helper("cascade@test.com")
        session1 = await create_session_helper(user.id)
        session2 = await create_session_helper(user.id)
        make_request_with_cookie(client, session1.id)

        response = client.delete("/account")

        assert response.status_code == 200

        # Verify both sessions are deleted
        deleted_session1 = await adapter.get_session(db_session, session1.id)
        deleted_session2 = await adapter.get_session(db_session, session2.id)
        assert deleted_session1 is None
        assert deleted_session2 is None

    @pytest.mark.asyncio
    async def test_delete_user_cascade_deletes_single_account(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        create_account_helper,
        make_request_with_cookie,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test that deleting user also deletes their OAuth account."""
        user = await create_user_helper("accountdel@test.com")
        session = await create_session_helper(user.id)
        account = await create_account_helper(user.id, provider="google")
        make_request_with_cookie(client, session.id)

        response = client.delete("/account")

        assert response.status_code == 200

        # Verify account is deleted
        deleted_account = await adapter.get_account_by_user_and_provider(db_session, user.id, "google")
        assert deleted_account is None

    @pytest.mark.asyncio
    async def test_delete_user_cascade_deletes_multiple_accounts(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        create_account_helper,
        make_request_with_cookie,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test that all OAuth accounts are deleted when user is deleted."""
        user = await create_user_helper("multi@test.com")
        session = await create_session_helper(user.id)
        google_account = await create_account_helper(user.id, provider="google")
        github_account = await create_account_helper(user.id, provider="github")
        make_request_with_cookie(client, session.id)

        response = client.delete("/account")

        assert response.status_code == 200

        # Verify both accounts are deleted
        deleted_google = await adapter.get_account_by_user_and_provider(db_session, user.id, "google")
        deleted_github = await adapter.get_account_by_user_and_provider(db_session, user.id, "github")
        assert deleted_google is None
        assert deleted_github is None

    @pytest.mark.asyncio
    async def test_delete_user_cascade_deletes_all_related_data(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        create_account_helper,
        make_request_with_cookie,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test comprehensive cascade deletion."""
        user = await create_user_helper("fullcascade@test.com")
        session1 = await create_session_helper(user.id)
        session2 = await create_session_helper(user.id)
        google_account = await create_account_helper(user.id, provider="google")
        github_account = await create_account_helper(user.id, provider="github")
        make_request_with_cookie(client, session1.id)

        response = client.delete("/account")

        assert response.status_code == 200

        # Verify everything is deleted
        deleted_user = await adapter.get_user_by_id(db_session, user.id)
        deleted_session1 = await adapter.get_session(db_session, session1.id)
        deleted_session2 = await adapter.get_session(db_session, session2.id)
        deleted_google = await adapter.get_account_by_user_and_provider(db_session, user.id, "google")
        deleted_github = await adapter.get_account_by_user_and_provider(db_session, user.id, "github")

        assert deleted_user is None
        assert deleted_session1 is None
        assert deleted_session2 is None
        assert deleted_google is None
        assert deleted_github is None


class TestGetUserFromSession:
    """Tests for BelgieClient.get_user_from_session() method."""

    @pytest.mark.asyncio
    async def test_get_user_from_session_success(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
    ):
        """Test retrieving user by session ID."""
        user = await create_user_helper("lookup@test.com")
        session = await create_session_helper(user.id)

        response = client.get(f"/admin/get-user-by-session/{session.id}")

        assert response.status_code == 200
        json = response.json()
        assert json["id"] == str(user.id)
        assert json["email"] == "lookup@test.com"

    @pytest.mark.asyncio
    async def test_get_user_from_session_not_found(self, client: TestClient):
        """Test that nonexistent session returns 404."""
        fake_session_id = uuid4()

        response = client.get(f"/admin/get-user-by-session/{fake_session_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_user_from_session_expired_returns_404(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
    ):
        """Test that expired session returns 404."""
        user = await create_user_helper("expired@test.com")
        expired_time = datetime.now(UTC) - timedelta(hours=1)
        session = await create_session_helper(user.id, expires_at=expired_time)

        response = client.get(f"/admin/get-user-by-session/{session.id}")

        assert response.status_code == 404


class TestSignOut:
    """Tests for BelgieClient.sign_out() method."""

    @pytest.mark.asyncio
    async def test_sign_out_success(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test signing out successfully deletes session."""
        user = await create_user_helper("signout@test.com")
        session = await create_session_helper(user.id)

        response = client.post(f"/admin/signout-user/{session.id}")

        assert response.status_code == 200
        assert response.json()["signed_out"] is True

        # Verify session is deleted from database
        deleted_session = await adapter.get_session(db_session, session.id)
        assert deleted_session is None

    @pytest.mark.asyncio
    async def test_sign_out_nonexistent_session_returns_false(self, client: TestClient):
        """Test signing out nonexistent session returns false."""
        fake_session_id = uuid4()

        response = client.post(f"/admin/signout-user/{fake_session_id}")

        assert response.status_code == 200
        assert response.json()["signed_out"] is False

    @pytest.mark.asyncio
    async def test_sign_out_user_still_exists(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        adapter: AlchemyAdapter,
        db_session: AsyncSession,
    ):
        """Test that signing out doesn't delete the user."""
        user = await create_user_helper("staysalive@test.com")
        session = await create_session_helper(user.id)

        response = client.post(f"/admin/signout-user/{session.id}")

        assert response.status_code == 200

        # Verify user still exists
        existing_user = await adapter.get_user_by_id(db_session, user.id)
        assert existing_user is not None
        assert existing_user.email == "staysalive@test.com"


class TestCookieHandling:
    """Tests for cookie extraction and validation."""

    @pytest.mark.asyncio
    async def test_cookie_extraction_success(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that valid cookie is extracted correctly."""
        user = await create_user_helper("cookie@test.com")
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        response = client.get("/me")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cookie_with_different_name_ignored(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
    ):
        """Test that cookie with wrong name is ignored."""
        user = await create_user_helper("wrongcookie@test.com")
        session = await create_session_helper(user.id)
        client.cookies.set("wrong_cookie_name", str(session.id))

        response = client.get("/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_cookie_with_malformed_uuid(
        self,
        client: TestClient,
        auth_settings: BelgieSettings,
    ):
        """Test various malformed UUID formats."""
        malformed_values = [
            "not-a-uuid",
            "12345",
            "",
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "g0000000-0000-0000-0000-000000000000",
        ]

        for value in malformed_values:
            client.cookies.clear()
            client.cookies.set(auth_settings.cookie.name, value)
            response = client.get("/me")
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_cookie_with_empty_value(
        self,
        client: TestClient,
        auth_settings: BelgieSettings,
    ):
        """Test empty cookie value."""
        client.cookies.set(auth_settings.cookie.name, "")

        response = client.get("/me")

        assert response.status_code == 401


class TestEdgeCases:
    """Edge cases and stress tests."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_same_session(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test multiple concurrent requests with same session."""
        user = await create_user_helper("concurrent@test.com")
        session = await create_session_helper(user.id)
        make_request_with_cookie(client, session.id)

        # Make multiple requests in quick succession
        responses = [
            client.get("/me"),
            client.get("/session/info"),
            client.get("/me"),
        ]

        for response in responses:
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_user_with_multiple_active_sessions(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test that user can have multiple active sessions."""
        user = await create_user_helper("multisession@test.com")
        session1 = await create_session_helper(user.id)
        session2 = await create_session_helper(user.id)

        # Test with first session
        make_request_with_cookie(client, session1.id)
        response1 = client.get("/me")
        assert response1.status_code == 200

        # Test with second session
        client.cookies.clear()
        make_request_with_cookie(client, session2.id)
        response2 = client.get("/me")
        assert response2.status_code == 200

    @pytest.mark.asyncio
    async def test_session_near_expiry_boundary(
        self,
        client: TestClient,
        create_user_helper,
        create_session_helper,
        make_request_with_cookie,
    ):
        """Test session behavior exactly at update_age threshold."""
        user = await create_user_helper("boundary@test.com")

        # Session expires in exactly 15 minutes (the update_age threshold)
        boundary_time = datetime.now(UTC) + timedelta(minutes=15)
        session = await create_session_helper(user.id, expires_at=boundary_time)
        make_request_with_cookie(client, session.id)

        response = client.get("/me")

        # Should still work
        assert response.status_code == 200
