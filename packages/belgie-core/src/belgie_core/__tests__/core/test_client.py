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
async def test_get_user_success(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.user_id = uuid4()
    user = MagicMock()
    user.scopes = []

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_user_by_id.return_value = user

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    result = await client.get_user(SecurityScopes(), request)

    assert result == user
    mock_adapter.get_user_by_id.assert_called_once_with(client.db, session.user_id)


@pytest.mark.asyncio
async def test_get_user_with_scopes_success(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.user_id = uuid4()
    user = MagicMock()
    user.scopes = ["read", "write"]

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_user_by_id.return_value = user

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    result = await client.get_user(SecurityScopes(scopes=["read"]), request)

    assert result == user


@pytest.mark.asyncio
async def test_get_user_no_cookie_raises_401(client):
    request = MagicMock()
    request.cookies.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await client.get_user(SecurityScopes(), request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "not authenticated"


@pytest.mark.asyncio
async def test_get_user_no_session_raises_401(client, mock_session_manager):
    mock_session_manager.get_session.return_value = None

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await client.get_user(SecurityScopes(), request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "not authenticated"


@pytest.mark.asyncio
async def test_get_user_user_not_found_raises_401(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.user_id = uuid4()

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_user_by_id.return_value = None

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await client.get_user(SecurityScopes(), request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "user not found"


@pytest.mark.asyncio
async def test_get_user_insufficient_scopes_raises_403(client, mock_adapter, mock_session_manager):
    session = MagicMock()
    session.user_id = uuid4()
    user = MagicMock()
    user.scopes = ["read"]

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_user_by_id.return_value = user

    request = MagicMock()
    request.cookies.get.return_value = str(uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await client.get_user(SecurityScopes(scopes=["admin"]), request)

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
async def test_delete_user_calls_adapter_delete(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.delete_user.return_value = True

    result = await client.delete_user(user)

    assert result is True
    mock_adapter.delete_user.assert_called_once_with(client.db, user.id)


@pytest.mark.asyncio
async def test_delete_user_returns_false_if_not_found(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.delete_user.return_value = False

    result = await client.delete_user(user)

    assert result is False


@pytest.mark.asyncio
async def test_get_user_from_session_success(client, mock_adapter, mock_session_manager):
    session_id = uuid4()
    session = MagicMock()
    session.user_id = uuid4()
    user = MagicMock()

    mock_session_manager.get_session.return_value = session
    mock_adapter.get_user_by_id.return_value = user

    result = await client.get_user_from_session(session_id)

    assert result == user
    mock_session_manager.get_session.assert_called_once_with(client.db, session_id)
    mock_adapter.get_user_by_id.assert_called_once_with(client.db, session.user_id)


@pytest.mark.asyncio
async def test_get_user_from_session_no_session_returns_none(client, mock_session_manager):
    session_id = uuid4()
    mock_session_manager.get_session.return_value = None

    result = await client.get_user_from_session(session_id)

    assert result is None


@pytest.mark.asyncio
async def test_sign_out_success(client, mock_session_manager):
    session_id = uuid4()
    mock_session_manager.delete_session.return_value = True

    result = await client.sign_out(session_id)

    assert result is True
    mock_session_manager.delete_session.assert_called_once_with(client.db, session_id)


@pytest.mark.asyncio
async def test_sign_out_returns_false_if_session_not_found(client, mock_session_manager):
    session_id = uuid4()
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

    adapter.get_user_by_email.return_value = None
    adapter.create_user.return_value = user
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
        name="Test User",
    )

    assert created_user is user
    assert created_session is session
    adapter.create_user.assert_called_once_with(
        mock_db,
        email="user@example.com",
        name="Test User",
        image=None,
        email_verified=False,
    )
    session_manager.create_session.assert_called_once_with(
        mock_db,
        user_id=user.id,
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

    adapter.get_user_by_email.return_value = user
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
    adapter.create_user.assert_not_called()
    session_manager.create_session.assert_called_once_with(
        mock_db,
        user_id=user.id,
        ip_address=None,
        user_agent=None,
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

    adapter.get_user_by_email.return_value = user
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
        user_id=user.id,
        ip_address="127.0.0.1",
        user_agent="test-agent",
    )
