from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import Mock
from uuid import UUID, uuid4

from belgie_alchemy import AlchemyAdapter
from belgie_proto import (
    AccountProtocol,
    AdapterProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from fastapi import APIRouter
from pydantic import Field
from pydantic_settings import BaseSettings

from belgie.auth.core.settings import CookieSettings
from belgie.auth.providers.protocols import OAuthProviderProtocol


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
    """Verify AlchemyAdapter implements AdapterProtocol using runtime checks."""

    adapter = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
    )

    # Runtime protocol check - AdapterProtocol is now runtime_checkable
    assert isinstance(adapter, AdapterProtocol)

    # Verify all required methods are callable
    assert callable(adapter.create_user)
    assert callable(adapter.get_user_by_id)
    assert callable(adapter.get_user_by_email)
    assert callable(adapter.update_user)
    assert callable(adapter.create_account)
    assert callable(adapter.get_account)
    assert callable(adapter.get_account_by_user_and_provider)
    assert callable(adapter.update_account)
    assert callable(adapter.create_session)
    assert callable(adapter.get_session)
    assert callable(adapter.update_session)
    assert callable(adapter.delete_session)
    assert callable(adapter.delete_expired_sessions)
    assert callable(adapter.create_oauth_state)
    assert callable(adapter.get_oauth_state)
    assert callable(adapter.delete_oauth_state)
    assert callable(adapter.delete_user)


def test_alchemy_adapter_no_longer_has_dependency() -> None:
    """AlchemyAdapter no longer exposes dependency property."""

    adapter = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
    )

    # Verify adapter is valid but doesn't have dependency property
    assert isinstance(adapter, AdapterProtocol)
    assert not hasattr(adapter, "dependency")


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
        adapter: AdapterProtocol,  # noqa: ARG002
        cookie_settings: CookieSettings,
        session_max_age: int,
        signin_redirect: str,
        signout_redirect: str,  # noqa: ARG002
        hook_runner,  # noqa: ARG002
        db_dependency,  # noqa: ARG002
    ) -> APIRouter:
        router = APIRouter(prefix=f"/{self.provider_id}", tags=["auth", "oauth"])

        @router.get("/signin")
        async def signin() -> dict[str, str]:
            return {"message": "signin", "redirect": signin_redirect}

        @router.get("/callback")
        async def callback() -> dict[str, str]:
            return {
                "message": "callback",
                "secure": str(cookie_settings.secure),
                "session_max_age": str(session_max_age),
            }

        return router


def test_mock_provider_satisfies_oauth_provider_protocol() -> None:
    """Verify MockOAuthProvider implements OAuthProviderProtocol using runtime checks."""
    settings = MockProviderSettings()
    provider = MockOAuthProvider(settings)

    # Runtime protocol check - OAuthProviderProtocol is now runtime_checkable
    assert isinstance(provider, OAuthProviderProtocol)

    # Verify provider_id property
    assert hasattr(provider, "provider_id")
    assert provider.provider_id == "mock"

    # Verify get_router method is callable and returns proper type
    assert callable(provider.get_router)

    adapter = AlchemyAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
    )
    cookie_settings = CookieSettings()

    # Mock hook_runner and db_dependency for the test
    mock_hook_runner = Mock()
    mock_db_dependency = Mock()

    router = provider.get_router(
        adapter,
        cookie_settings,
        session_max_age=3600,
        signin_redirect="/dashboard",
        signout_redirect="/",
        hook_runner=mock_hook_runner,
        db_dependency=mock_db_dependency,
    )
    assert isinstance(router, APIRouter)
    assert router.prefix == "/mock"

    # Verify router has expected routes (paths include prefix)
    route_paths = [route.path for route in router.routes]
    assert "/mock/signin" in route_paths
    assert "/mock/callback" in route_paths
