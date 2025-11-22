from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import Field
from pydantic_settings import BaseSettings

from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.protocols.adapter import AdapterProtocol
from belgie.auth.protocols.models import AccountProtocol, OAuthStateProtocol, SessionProtocol, UserProtocol
from belgie.auth.protocols.provider import OAuthProviderProtocol  # noqa: TC001


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
        access_token="token",  # noqa: S106
        refresh_token="refresh",  # noqa: S106
        expires_at=now,
        token_type="Bearer",  # noqa: S106
        scope="openid email",
        id_token="id_token",  # noqa: S106
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
    adapter: AdapterProtocol = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
        db_dependency=None,
    )

    # Check that get_db method exists and returns correct type
    assert hasattr(adapter, "get_db")
    assert callable(adapter.get_db)
    db_func = adapter.get_db()
    assert db_func is None  # Since we passed None


def test_alchemy_adapter_get_db_with_dependency() -> None:
    """Verify AlchemyAdapter.get_db returns the provided dependency."""

    async def mock_db_dependency() -> None:
        pass

    adapter = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
        db_dependency=mock_db_dependency,
    )

    db_func = adapter.get_db()
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

    def get_router(self, _adapter: AdapterProtocol) -> APIRouter:
        router = APIRouter(prefix=f"/{self.provider_id}", tags=["auth", "oauth"])

        @router.get("/signin")
        async def signin() -> dict[str, str]:
            return {"message": "signin"}

        @router.get("/callback")
        async def callback() -> dict[str, str]:
            return {"message": "callback"}

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

    # Create a mock adapter and get router
    adapter = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
        db_dependency=None,
    )

    router = provider.get_router(adapter)
    assert isinstance(router, APIRouter)
    assert router.prefix == "/mock"
