from dataclasses import dataclass
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from belgie_core.core.belgie import Belgie


@dataclass(slots=True, kw_only=True, frozen=True)
class DummyPluginSettings:
    pass


class DummyPlugin:
    def __init__(self, _belgie_settings: object, _settings: DummyPluginSettings) -> None:
        pass

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        router = APIRouter()

        @router.get("/dummy")
        def dummy_route() -> dict[str, str]:
            return {"message": "hello plugin"}

        return router

    def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return APIRouter()


@pytest.fixture
def belgie_instance() -> Belgie:
    settings = Mock()
    settings.session.max_age = 3600
    settings.session.update_age = 600
    settings.urls.signin_redirect = "/signin"
    settings.urls.signout_redirect = "/signout"
    settings.cookie.name = "belgie_session"
    settings.cookie.domain = None

    adapter = Mock()
    # Mock db dependency
    db = Mock()
    db.dependency = lambda: None

    return Belgie(settings=settings, adapter=adapter, db=db)


def test_plugin_router_included(belgie_instance: Belgie) -> None:
    belgie_instance.add_plugin(DummyPlugin, DummyPluginSettings())

    app = FastAPI()
    app.include_router(belgie_instance.router)

    client = TestClient(app)
    response = client.get("/auth/dummy")
    assert response.status_code == 200
    assert response.json() == {"message": "hello plugin"}


def test_multiple_plugins(belgie_instance: Belgie) -> None:
    class PluginA(DummyPlugin):
        def router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
            router = APIRouter()

            @router.get("/a")
            def route_a() -> dict[str, str]:
                return {"val": "a"}

            return router

        def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
            return APIRouter()

    class PluginB(DummyPlugin):
        def router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
            router = APIRouter()

            @router.get("/b")
            def route_b() -> dict[str, str]:
                return {"val": "b"}

            return router

        def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
            return APIRouter()

    belgie_instance.add_plugin(PluginA, DummyPluginSettings())
    belgie_instance.add_plugin(PluginB, DummyPluginSettings())

    app = FastAPI()
    app.include_router(belgie_instance.router)
    client = TestClient(app)

    assert client.get("/auth/a").status_code == 200
    assert client.get("/auth/b").status_code == 200


def test_plugin_public_included(belgie_instance: Belgie) -> None:
    class RootPlugin(DummyPlugin):
        def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
            router = APIRouter()

            @router.get("/root")
            def root_route() -> dict[str, str]:
                return {"message": "root"}

            return router

    belgie_instance.add_plugin(RootPlugin, DummyPluginSettings())

    app = FastAPI()
    app.include_router(belgie_instance.router)

    client = TestClient(app)
    response = client.get("/root")
    assert response.status_code == 200
    assert response.json() == {"message": "root"}


def test_plugin_router_none_public_included(belgie_instance: Belgie) -> None:
    class PublicOnlyPlugin(DummyPlugin):
        def router(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
            return None

        def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
            router = APIRouter()

            @router.get("/public-only")
            def public_route() -> dict[str, str]:
                return {"message": "public"}

            return router

    belgie_instance.add_plugin(PublicOnlyPlugin, DummyPluginSettings())

    app = FastAPI()
    app.include_router(belgie_instance.router)
    client = TestClient(app)

    assert client.get("/auth/dummy").status_code == 404
    response = client.get("/public-only")
    assert response.status_code == 200
    assert response.json() == {"message": "public"}


def test_plugin_public_none_router_included(belgie_instance: Belgie) -> None:
    class AuthOnlyPlugin(DummyPlugin):
        def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
            return None

    belgie_instance.add_plugin(AuthOnlyPlugin, DummyPluginSettings())

    app = FastAPI()
    app.include_router(belgie_instance.router)
    client = TestClient(app)

    assert client.get("/auth/dummy").status_code == 200
    assert client.get("/root").status_code == 404


def test_plugin_router_and_public_none_keeps_signout_route(belgie_instance: Belgie) -> None:
    class NoRoutesPlugin(DummyPlugin):
        def router(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
            return None

        def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
            return None

    belgie_instance.add_plugin(NoRoutesPlugin, DummyPluginSettings())

    app = FastAPI()
    app.include_router(belgie_instance.router)
    client = TestClient(app)

    assert client.get("/auth/dummy").status_code == 404
    assert client.get("/root").status_code == 404
    assert any(route.path == "/auth/signout" for route in app.routes)
    assert client.post("/auth/signout", follow_redirects=False).status_code == 302
