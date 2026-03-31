from datetime import UTC, datetime
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from belgie_core.core.client import BelgieClient
from belgie_core.core.settings import CookieSettings
from fastapi import HTTPException, Response
from fastapi.security import SecurityScopes


@pytest.fixture
def mock_adapter():
    return AsyncMock()


@pytest.fixture
def mock_session_manager():
    manager = AsyncMock()
    manager.max_age = 3600
    return manager


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def client(mock_db, mock_adapter, mock_session_manager):
    return BelgieClient(
        db=mock_db,
        adapter=mock_adapter,
        session_manager=mock_session_manager,
        cookie_settings=CookieSettings(name="test_session"),
    )


@pytest.mark.asyncio
async def test_init_captures_dependencies(mock_db, mock_adapter, mock_session_manager):
    client = BelgieClient(
        db=mock_db,
        adapter=mock_adapter,
        session_manager=mock_session_manager,
        cookie_settings=CookieSettings(name="my_session"),
    )

    assert client.db == mock_db
    assert client.adapter == mock_adapter
    assert client.session_manager == mock_session_manager
    assert client.cookie_settings.name == "my_session"


@pytest.mark.asyncio
async def test_get_session_from_cookie_success(client, mock_session_manager):
    session_id = uuid4()
    mock_session = MagicMock()
    mock_session_manager.get_session.return_value = mock_session

    request = MagicMock()
    request.cookies.get.return_value = str(session_id)

    result = await client._get_session_from_cookie(request)

    assert result == mock_session
    request.cookies.get.assert_called_once_with("test_session")
    mock_session_manager.get_session.assert_called_once_with(client.db, session_id)


@pytest.mark.asyncio
async def test_get_session_from_cookie_no_cookie(client):
    request = MagicMock()
    request.cookies.get.return_value = None

    result = await client._get_session_from_cookie(request)

    assert result is None


@pytest.mark.asyncio
async def test_get_session_from_cookie_invalid_uuid(client):
    request = MagicMock()
    request.cookies.get.return_value = "invalid-uuid"

    result = await client._get_session_from_cookie(request)

    assert result is None


@pytest.mark.asyncio
async def test_get_individual_success(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.individual_id = uuid4()
    user = MagicMock()
    user.scopes = []

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_individual_by_id.return_value = user

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    result = await client.get_individual(SecurityScopes(), request)

    assert result == user
    mock_adapter.get_individual_by_id.assert_called_once_with(client.db, session.individual_id)


@pytest.mark.asyncio
async def test_get_individual_with_scopes_success(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.individual_id = uuid4()
    user = MagicMock()
    user.scopes = ["read", "write"]

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_individual_by_id.return_value = user

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    result = await client.get_individual(SecurityScopes(scopes=["read"]), request)

    assert result == user


@pytest.mark.asyncio
async def test_get_individual_no_cookie_raises_401(client):
    request = MagicMock()
    request.cookies.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await client.get_individual(SecurityScopes(), request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "not authenticated"


@pytest.mark.asyncio
async def test_get_individual_no_session_raises_401(client, mock_session_manager):
    mock_session_manager.get_session.return_value = None

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await client.get_individual(SecurityScopes(), request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "not authenticated"


@pytest.mark.asyncio
async def test_get_individual_user_not_found_raises_401(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.individual_id = uuid4()

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_individual_by_id.return_value = None

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await client.get_individual(SecurityScopes(), request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "individual not found"


@pytest.mark.asyncio
async def test_get_individual_insufficient_scopes_raises_403(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.individual_id = uuid4()
    user = MagicMock()
    user.scopes = ["read"]

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_individual_by_id.return_value = user

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await client.get_individual(SecurityScopes(scopes=["admin"]), request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient permissions"


@pytest.mark.asyncio
async def test_get_session_success(client, mock_session_manager):
    mock_session = MagicMock()
    mock_session_manager.get_session.return_value = mock_session

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    result = await client.get_session(request)

    assert result == mock_session


@pytest.mark.asyncio
async def test_get_session_no_cookie_raises_401(client):
    request = MagicMock()
    request.cookies.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await client.get_session(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "not authenticated"


@pytest.mark.asyncio
async def test_delete_individual_calls_adapter_delete(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.delete_individual.return_value = True

    result = await client.delete_individual(user)

    assert result is True
    mock_adapter.delete_individual.assert_called_once_with(client.db, user.id)


@pytest.mark.asyncio
async def test_delete_individual_returns_false_if_not_found(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.delete_individual.return_value = False

    result = await client.delete_individual(user)

    assert result is False


@pytest.mark.asyncio
async def test_get_individual_from_session_success(client, mock_adapter, mock_session_manager):
    session_id = uuid4()
    session = MagicMock()
    session.individual_id = uuid4()
    user = MagicMock()

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_individual_by_id.return_value = user

    result = await client.get_individual_from_session(session_id)

    assert result == user
    mock_session_manager.get_session.assert_called_once_with(client.db, session_id)
    mock_adapter.get_individual_by_id.assert_called_once_with(client.db, session.individual_id)


@pytest.mark.asyncio
async def test_get_individual_from_session_no_session_returns_none(client, mock_session_manager):
    session_id = uuid4()
    mock_session_manager.get_session.return_value = None

    result = await client.get_individual_from_session(session_id)

    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_individual_creates_and_marks_created(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.get_individual_by_email.return_value = None
    mock_adapter.create_individual.return_value = user

    result_user, created = await client.get_or_create_individual("new@example.com", name="New Individual")

    assert result_user is user
    assert created is True
    mock_adapter.create_individual.assert_called_once_with(
        client.db,
        email="new@example.com",
        name="New Individual",
        image=None,
        email_verified_at=None,
    )


@pytest.mark.asyncio
async def test_get_or_create_individual_forwards_email_verified_at(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    verified_at = datetime(2024, 1, 1, tzinfo=UTC)
    mock_adapter.get_individual_by_email.return_value = None
    mock_adapter.create_individual.return_value = user

    await client.get_or_create_individual("new@example.com", email_verified_at=verified_at)

    mock_adapter.create_individual.assert_called_once_with(
        client.db,
        email="new@example.com",
        name=None,
        image=None,
        email_verified_at=verified_at,
    )


@pytest.mark.asyncio
async def test_get_or_create_individual_returns_existing_user(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.get_individual_by_email.return_value = user

    result_user, created = await client.get_or_create_individual("existing@example.com")

    assert result_user is user
    assert created is False
    mock_adapter.create_individual.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_oauth_account_creates_when_missing(client, mock_adapter):
    individual_id = uuid4()
    account = MagicMock()
    mock_adapter.get_account_by_individual_and_provider.return_value = None
    mock_adapter.create_account.return_value = account

    result = await client.upsert_oauth_account(
        individual_id=individual_id,
        provider="google",
        provider_account_id="google-123",
        access_token="access-token",
    )

    assert result is account
    mock_adapter.update_account.assert_not_called()
    mock_adapter.create_account.assert_called_once_with(
        client.db,
        individual_id=individual_id,
        provider="google",
        provider_account_id="google-123",
        access_token="access-token",
    )


@pytest.mark.asyncio
async def test_upsert_oauth_account_updates_when_existing(client, mock_adapter):
    individual_id = uuid4()
    existing_account = MagicMock()
    updated_account = MagicMock()
    mock_adapter.get_account_by_individual_and_provider.return_value = existing_account
    mock_adapter.update_account.return_value = updated_account

    result = await client.upsert_oauth_account(
        individual_id=individual_id,
        provider="google",
        provider_account_id="google-123",
        access_token="new-access-token",
    )

    assert result is updated_account
    mock_adapter.update_account.assert_called_once_with(
        client.db,
        individual_id=individual_id,
        provider="google",
        access_token="new-access-token",
    )
    mock_adapter.create_account.assert_not_called()


@pytest.mark.asyncio
async def test_sign_in_individual_derives_ip_and_user_agent(client, mock_session_manager):
    user = MagicMock()
    user.id = uuid4()
    session = MagicMock()
    session.id = uuid4()
    mock_session_manager.create_session.return_value = session

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers.get.return_value = "test-agent"

    result = await client.sign_in_individual(user, request=request)

    assert result is session
    mock_session_manager.create_session.assert_called_once_with(
        client.db,
        individual_id=user.id,
        ip_address="127.0.0.1",
        user_agent="test-agent",
    )


@pytest.mark.asyncio
async def test_sign_out_success(client, mock_adapter, mock_session_manager):
    session_id = uuid4()
    session = MagicMock()
    mock_session_manager.delete_session.return_value = True
    mock_session_manager.get_session.return_value = session

    result = await client.sign_out(session_id)

    assert result is True
    mock_session_manager.get_session.assert_called_once_with(client.db, session_id)
    mock_session_manager.delete_session.assert_called_once_with(client.db, session_id)
    mock_adapter.get_individual_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_sign_out_returns_false_if_session_not_found(client, mock_session_manager):
    session_id = uuid4()
    mock_session_manager.get_session.return_value = None
    mock_session_manager.delete_session.return_value = False

    result = await client.sign_out(session_id)

    assert result is False


@pytest.mark.asyncio
async def test_sign_up_creates_user_sets_cookie_and_returns_user_session(mock_db):
    adapter = AsyncMock()
    session_manager = AsyncMock()
    session_manager.max_age = 7200
    user = MagicMock()
    user.id = uuid4()
    session = MagicMock()
    session.id = uuid4()

    adapter.get_individual_by_email.return_value = None
    adapter.create_individual.return_value = user
    session_manager.create_session.return_value = session

    client = BelgieClient(
        db=mock_db,
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(
            name="test_session",
            secure=True,
            http_only=True,
            same_site="strict",
            domain="example.com",
        ),
    )

    created_user, created_session = await client.sign_up(
        "user@example.com",
        name="Test Individual",
    )

    assert created_user is user
    assert created_session is session
    adapter.create_individual.assert_called_once_with(
        mock_db,
        email="user@example.com",
        name="Test Individual",
        image=None,
        email_verified_at=None,
    )
    session_manager.create_session.assert_called_once_with(
        mock_db,
        individual_id=user.id,
        ip_address=None,
        user_agent=None,
    )

    response = client.create_session_cookie(session, Response())
    set_cookie_header = response.headers.get("set-cookie")
    assert set_cookie_header is not None
    cookie = SimpleCookie()
    cookie.load(set_cookie_header)
    assert cookie["test_session"].value == str(session.id)
    assert cookie["test_session"]["max-age"] == str(session_manager.max_age)
    assert cookie["test_session"]["domain"] == "example.com"
    assert cookie["test_session"]["samesite"] == "strict"
    assert "HttpOnly" in set_cookie_header
    assert "Secure" in set_cookie_header


@pytest.mark.asyncio
async def test_sign_up_existing_user_skips_create(mock_db):
    adapter = AsyncMock()
    session_manager = AsyncMock()
    session_manager.max_age = 3600
    user = MagicMock()
    user.id = uuid4()
    session = MagicMock()
    session.id = uuid4()

    adapter.get_individual_by_email.return_value = user
    session_manager.create_session.return_value = session

    client = BelgieClient(
        db=mock_db,
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="test_session"),
    )

    created_user, created_session = await client.sign_up(
        "user@example.com",
    )

    assert created_user is user
    assert created_session is session
    adapter.create_individual.assert_not_called()
    session_manager.create_session.assert_called_once_with(
        mock_db,
        individual_id=user.id,
        ip_address=None,
        user_agent=None,
    )


@pytest.mark.asyncio
async def test_sign_up_forwards_email_verified_at(mock_db):
    adapter = AsyncMock()
    session_manager = AsyncMock()
    session_manager.max_age = 3600
    user = MagicMock()
    user.id = uuid4()
    session = MagicMock()
    session.id = uuid4()
    verified_at = datetime(2024, 1, 1, tzinfo=UTC)

    adapter.get_individual_by_email.return_value = None
    adapter.create_individual.return_value = user
    session_manager.create_session.return_value = session

    client = BelgieClient(
        db=mock_db,
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="test_session"),
    )

    await client.sign_up(
        "user@example.com",
        email_verified_at=verified_at,
    )

    adapter.create_individual.assert_called_once_with(
        mock_db,
        email="user@example.com",
        name=None,
        image=None,
        email_verified_at=verified_at,
    )


@pytest.mark.asyncio
async def test_sign_up_derives_ip_and_user_agent_from_request(mock_db):
    adapter = AsyncMock()
    session_manager = AsyncMock()
    session_manager.max_age = 3600
    user = MagicMock()
    user.id = uuid4()
    session = MagicMock()
    session.id = uuid4()

    adapter.get_individual_by_email.return_value = user
    session_manager.create_session.return_value = session

    request = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers.get.return_value = "test-agent"

    client = BelgieClient(
        db=mock_db,
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="test_session"),
    )

    await client.sign_up(
        "user@example.com",
        request=request,
    )

    session_manager.create_session.assert_called_once_with(
        mock_db,
        individual_id=user.id,
        ip_address="127.0.0.1",
        user_agent="test-agent",
    )


@pytest.mark.asyncio
async def test_sign_up_calls_after_sign_up_for_new_user(mock_db):
    adapter = AsyncMock()
    session_manager = AsyncMock()
    session_manager.max_age = 3600
    user = MagicMock()
    user.id = uuid4()
    session = MagicMock()
    request = MagicMock()
    after_sign_up = AsyncMock()

    adapter.get_individual_by_email.return_value = None
    adapter.create_individual.return_value = user
    session_manager.create_session.return_value = session

    client = BelgieClient(
        db=mock_db,
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="test_session"),
        after_sign_up=after_sign_up,
    )

    await client.sign_up("user@example.com", request=request)

    after_sign_up.assert_awaited_once_with(
        client=client,
        request=request,
        individual=user,
    )


@pytest.mark.asyncio
async def test_sign_up_skips_after_sign_up_for_existing_user(mock_db):
    adapter = AsyncMock()
    session_manager = AsyncMock()
    session_manager.max_age = 3600
    user = MagicMock()
    user.id = uuid4()
    session = MagicMock()
    after_sign_up = AsyncMock()

    adapter.get_individual_by_email.return_value = user
    session_manager.create_session.return_value = session

    client = BelgieClient(
        db=mock_db,
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="test_session"),
        after_sign_up=after_sign_up,
    )

    await client.sign_up("user@example.com")

    after_sign_up.assert_not_awaited()
