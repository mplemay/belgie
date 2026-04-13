from collections.abc import Callable
from inspect import Parameter, signature
from types import SimpleNamespace
from typing import Annotated, get_args, get_origin
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Depends, FastAPI, Security
from fastapi.params import Depends as DependsParam
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient

from belgie_core.core.belgie import Belgie


def _alias_value(annotation: object) -> object:
    return annotation.__value__ if hasattr(annotation, "__value__") else annotation


@pytest.fixture
def db_provider() -> tuple[Callable[[], Mock], Mock]:
    db = Mock()

    async def get_db() -> Mock:
        return db

    return get_db, db


@pytest.fixture
def belgie_instance(db_provider: tuple[Callable[[], Mock], Mock]) -> Belgie:
    settings = Mock()
    settings.session.max_age = 3600
    settings.session.update_age = 600
    settings.urls.signin_redirect = "/signin"
    settings.urls.signout_redirect = "/signout"
    settings.cookie.name = "belgie_session"
    settings.cookie.domain = None

    adapter = Mock()
    dependency, _ = db_provider
    return Belgie(settings=settings, adapter=adapter, database=dependency)


def test_depends_belgie_user_route_registration_no_fastapi_error(belgie_instance: Belgie) -> None:
    app = FastAPI()

    @app.get("/user")
    async def user_route(user=Depends(belgie_instance.individual)) -> dict[str, bool]:
        return {"ok": user is not None}

    assert any(route.path == "/user" for route in app.routes)


def test_depends_belgie_session_route_registration_no_fastapi_error(belgie_instance: Belgie) -> None:
    app = FastAPI()

    @app.get("/session")
    async def session_route(session=Depends(belgie_instance.session)) -> dict[str, bool]:
        return {"ok": session is not None}

    assert any(route.path == "/session" for route in app.routes)


def test_user_property_signature_uses_depends(
    db_provider: tuple[Callable[[], Mock], Mock],
    belgie_instance: Belgie,
) -> None:
    dependency, _ = db_provider

    db_parameter = signature(belgie_instance.individual).parameters["db"]
    assert db_parameter.default is Parameter.empty
    annotation = _alias_value(db_parameter.annotation)
    assert get_origin(annotation) is Annotated

    _, depends_marker = get_args(annotation)
    assert isinstance(depends_marker, DependsParam)
    assert depends_marker.dependency is dependency


def test_session_property_signature_uses_depends(
    db_provider: tuple[Callable[[], Mock], Mock],
    belgie_instance: Belgie,
) -> None:
    dependency, _ = db_provider

    db_parameter = signature(belgie_instance.session).parameters["db"]
    assert db_parameter.default is Parameter.empty
    annotation = _alias_value(db_parameter.annotation)
    assert get_origin(annotation) is Annotated

    _, depends_marker = get_args(annotation)
    assert isinstance(depends_marker, DependsParam)
    assert depends_marker.dependency is dependency


def test_constructor_accepts_database_keyword() -> None:
    settings = Mock()
    settings.session.max_age = 3600
    settings.session.update_age = 600
    settings.urls.signin_redirect = "/signin"
    settings.urls.signout_redirect = "/signout"
    settings.cookie.name = "belgie_session"
    settings.cookie.domain = None
    adapter = Mock()

    def database() -> None:
        return None

    belgie = Belgie(settings=settings, adapter=adapter, database=database)

    assert belgie.database is database


def test_constructor_rejects_db_keyword() -> None:
    settings = Mock()
    settings.session.max_age = 3600
    settings.session.update_age = 600
    settings.urls.signin_redirect = "/signin"
    settings.urls.signout_redirect = "/signout"
    settings.cookie.name = "belgie_session"
    settings.cookie.domain = None
    adapter = Mock()

    def database() -> None:
        return None

    with pytest.raises(TypeError):
        Belgie(settings=settings, adapter=adapter, database=database, db=database)  # type: ignore[call-arg]


def test_constructor_rejects_hooks_keyword() -> None:
    settings = Mock()
    adapter = Mock()

    def database() -> None:
        return None

    with pytest.raises(TypeError):
        Belgie(settings=settings, adapter=adapter, database=database, hooks=database)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_individual_dependency_delegates_to_client_get_individual(belgie_instance: Belgie) -> None:
    mock_client = AsyncMock()
    mock_user = Mock()
    mock_client.get_individual.return_value = mock_user

    call_factory = Mock(return_value=mock_client)
    belgie_instance.__call__ = call_factory  # type: ignore[method-assign]

    request = Mock()
    security_scopes = SecurityScopes(scopes=["read"])
    db = Mock()

    result = await belgie_instance.individual(security_scopes, request, db)

    assert result is mock_user
    call_factory.assert_called_once_with(db)
    mock_client.get_individual.assert_awaited_once_with(security_scopes, request)


@pytest.mark.asyncio
async def test_session_dependency_delegates_to_client_get_session(belgie_instance: Belgie) -> None:
    mock_client = AsyncMock()
    mock_session = Mock()
    mock_client.get_session.return_value = mock_session

    call_factory = Mock(return_value=mock_client)
    belgie_instance.__call__ = call_factory  # type: ignore[method-assign]

    request = Mock()
    db = Mock()

    result = await belgie_instance.session(request, db)

    assert result is mock_session
    call_factory.assert_called_once_with(db)
    mock_client.get_session.assert_awaited_once_with(request)


def test_security_scope_forwarding_uses_security_scopes(belgie_instance: Belgie) -> None:
    mock_client = AsyncMock()
    mock_client.get_individual.return_value = SimpleNamespace(email="admin@example.com")

    call_factory = Mock(return_value=mock_client)
    belgie_instance.__call__ = call_factory  # type: ignore[method-assign]

    app = FastAPI()

    @app.get("/admin")
    async def admin_route(user=Security(belgie_instance.individual, scopes=["admin"])) -> dict[str, str]:
        return {"email": user.email}

    client = TestClient(app)
    response = client.get("/admin")

    assert response.status_code == 200
    assert response.json() == {"email": "admin@example.com"}

    security_scopes = mock_client.get_individual.await_args.args[0]
    assert isinstance(security_scopes, SecurityScopes)
    assert "admin" in security_scopes.scopes


def test_call_dependency_threads_after_sign_up_hook(
    db_provider: tuple[Callable[[], Mock], Mock],
    belgie_instance: Belgie,
) -> None:
    _dependency, db = db_provider

    client = belgie_instance(db)

    assert client.after_sign_up == belgie_instance.after_sign_up
