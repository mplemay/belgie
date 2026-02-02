from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from belgie_core.core.belgie import Belgie


class DummyPlugin:
    def __init__(self, belgie: Belgie, settings: dict[str, Any]) -> None:
        self.belgie = belgie
        self.settings = settings

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/dummy")
        def dummy_route() -> dict[str, str]:
            return {"message": "hello plugin"}

        return router


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
    belgie_instance.add_plugin(DummyPlugin, settings={})

    app = FastAPI()
    app.include_router(belgie_instance.router())

    client = TestClient(app)
    response = client.get("/auth/dummy")
    assert response.status_code == 200
    assert response.json() == {"message": "hello plugin"}


def test_multiple_plugins(belgie_instance: Belgie) -> None:
    class PluginA(DummyPlugin):
        def router(self) -> APIRouter:
            router = APIRouter()

            @router.get("/a")
            def route_a() -> dict[str, str]:
                return {"val": "a"}

            return router

    class PluginB(DummyPlugin):
        def router(self) -> APIRouter:
            router = APIRouter()

            @router.get("/b")
            def route_b() -> dict[str, str]:
                return {"val": "b"}

            return router

    belgie_instance.add_plugin(PluginA, settings={})
    belgie_instance.add_plugin(PluginB, settings={})

    app = FastAPI()
    app.include_router(belgie_instance.router())
    client = TestClient(app)

    assert client.get("/auth/a").status_code == 200
    assert client.get("/auth/b").status_code == 200
