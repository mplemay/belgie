from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from belgie_alchemy import AlchemyAdapter
from belgie_proto import (
    AccountProtocol,
    AdapterProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)


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
