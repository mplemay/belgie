# ruff: noqa: ANN001, ANN201, SLF001
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import SecurityScopes

from belgie.auth.core.client import AuthClient


@pytest.fixture
def mock_adapter():
    return AsyncMock()


@pytest.fixture
def mock_session_manager():
    return AsyncMock()


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def client(mock_db, mock_adapter, mock_session_manager):
    return AuthClient(
        db=mock_db,
        adapter=mock_adapter,
        session_manager=mock_session_manager,
        cookie_name="test_session",
    )


@pytest.mark.asyncio
async def test_init_captures_dependencies(mock_db, mock_adapter, mock_session_manager):
    client = AuthClient(
        db=mock_db,
        adapter=mock_adapter,
        session_manager=mock_session_manager,
        cookie_name="my_session",
    )

    assert client.db == mock_db
    assert client.adapter == mock_adapter
    assert client.session_manager == mock_session_manager
    assert client.cookie_name == "my_session"


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
async def test_delete_user_calls_adapter_cascade_delete(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.delete_user_cascade.return_value = True

    result = await client.delete_user(user)

    assert result is True
    mock_adapter.delete_user_cascade.assert_called_once_with(client.db, user.id)


@pytest.mark.asyncio
async def test_delete_user_returns_false_if_not_found(client, mock_adapter):
    user = MagicMock()
    user.id = uuid4()
    mock_adapter.delete_user_cascade.return_value = False

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
