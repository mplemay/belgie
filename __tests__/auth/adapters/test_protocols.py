from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import Field
from pydantic_settings import BaseSettings

from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.adapters.protocols import (
    AccountProtocol,
    AdapterProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from belgie.auth.core.settings import CookieSettings
from belgie.auth.providers.protocols import OAuthProviderProtocol  # noqa: TC001


@dataclass
class ExampleUser:
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str] | None = None
    custom_field: str | None = None


@dataclass
class ExampleAccount:
    id: UUID
    user_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    token_type: str | None
    scope: str | None
    id_token: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleSession:
    id: UUID
    user_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleOAuthState:
    id: UUID
    state: str
    code_verifier: str | None
    redirect_url: str | None
    created_at: datetime
    expires_at: datetime


def test_user_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    user = ExampleUser(
        id=uuid4(),
        email="test@example.com",
        email_verified=True,
        name="Test User",
        image="https://example.com/image.jpg",
        created_at=now,
        updated_at=now,
        scopes=[],
        custom_field="custom value",
    )

    assert isinstance(user, UserProtocol)


def test_account_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    account = ExampleAccount(
        id=uuid4(),
        user_id=uuid4(),
        provider="google",
        provider_account_id="12345",
        access_token="token",
        refresh_token="refresh",
        expires_at=now,
        token_type="Bearer",
        scope="openid email",
        id_token="id_token",
        created_at=now,
        updated_at=now,
    )

    assert isinstance(account, AccountProtocol)


def test_session_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    session = ExampleSession(
        id=uuid4(),
        user_id=uuid4(),
        expires_at=now,
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0",
        created_at=now,
        updated_at=now,
    )

    assert isinstance(session, SessionProtocol)


def test_oauth_state_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    oauth_state = ExampleOAuthState(
        id=uuid4(),
        state="random_state",
        code_verifier="verifier",
        redirect_url="/dashboard",
        created_at=now,
        expires_at=now,
    )

    assert isinstance(oauth_state, OAuthStateProtocol)


def test_user_with_custom_fields_satisfies_protocol() -> None:
    now = datetime.now(UTC)
    user = ExampleUser(
        id=uuid4(),
        email="test@example.com",
        email_verified=False,
        name=None,
        image=None,
        created_at=now,
        updated_at=now,
        scopes=[],
        custom_field="this is a custom field not in the protocol",
    )

    assert isinstance(user, UserProtocol)


def test_alchemy_adapter_satisfies_adapter_protocol() -> None:
    """Verify AlchemyAdapter implements AdapterProtocol."""

    async def mock_db_dependency() -> None:
        pass

    adapter: AdapterProtocol = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
        db_dependency=mock_db_dependency,
    )

    # Check that dependency property exists and returns correct type
    assert hasattr(adapter, "dependency")
    db_func = adapter.dependency
    assert db_func is mock_db_dependency
    assert callable(db_func)


def test_alchemy_adapter_dependency_property() -> None:
    """Verify AlchemyAdapter.dependency returns the provided dependency."""

    async def mock_db_dependency() -> None:
        pass

    adapter = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
        db_dependency=mock_db_dependency,
    )

    db_func = adapter.dependency
    assert db_func is mock_db_dependency


class MockProviderSettings(BaseSettings):
    """Mock provider settings for testing."""

    client_id: str = Field(default="test_client_id")
    client_secret: str = Field(default="test_secret")


class MockOAuthProvider:
    """Mock OAuth provider for testing protocol compliance."""

    def __init__(self, settings: MockProviderSettings) -> None:
        self.settings = settings

    @property
    def provider_id(self) -> Literal["mock"]:
        return "mock"

    def get_router(
        self,
        adapter: AdapterProtocol,
        cookie_settings: CookieSettings,
        session_max_age: int,
        signin_redirect: str,
        signout_redirect: str,  # noqa: ARG002
    ) -> APIRouter:
        router = APIRouter(prefix=f"/{self.provider_id}", tags=["auth", "oauth"])

        @router.get("/signin")
        async def signin() -> dict[str, str]:
            return {"message": "signin", "redirect": signin_redirect}

        @router.get("/callback")
        async def callback() -> dict[str, str]:
            # Use adapter and cookie_settings to verify they're accessible
            db_func = adapter.dependency
            return {
                "message": "callback",
                "secure": str(cookie_settings.secure),
                "has_db": str(callable(db_func)),
                "session_max_age": str(session_max_age),
            }

        return router


def test_mock_provider_satisfies_oauth_provider_protocol() -> None:
    """Verify MockOAuthProvider implements OAuthProviderProtocol."""
    settings = MockProviderSettings()
    provider: OAuthProviderProtocol = MockOAuthProvider(settings)

    # Check provider_id
    assert hasattr(provider, "provider_id")
    assert provider.provider_id == "mock"

    # Check get_router method
    assert hasattr(provider, "get_router")
    assert callable(provider.get_router)

    # Create a mock adapter and cookie settings
    async def mock_db_dependency() -> None:
        pass

    adapter = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
        db_dependency=mock_db_dependency,
    )
    cookie_settings = CookieSettings()

    router = provider.get_router(
        adapter,
        cookie_settings,
        session_max_age=3600,
        signin_redirect="/dashboard",
        signout_redirect="/",
    )
    assert isinstance(router, APIRouter)
    assert router.prefix == "/mock"
