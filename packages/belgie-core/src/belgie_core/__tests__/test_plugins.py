from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import APIRouter

from belgie_core.core.belgie import Belgie


class MockPlugin:
    def __init__(self, auth: Belgie, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        self.auth = auth
        self.args = args
        self.kwargs = kwargs

    @property
    def router(self) -> APIRouter:
        return APIRouter()


@pytest.fixture
def belgie_instance() -> Belgie:
    settings = Mock()
    settings.session.max_age = 3600
    settings.session.update_age = 600

    adapter = Mock()
    db = Mock()

    return Belgie(settings=settings, adapter=adapter, db=db)


def test_add_plugin_stores_instance(belgie_instance: Belgie) -> None:
    plugin = belgie_instance.add_plugin(MockPlugin)
    assert isinstance(plugin, MockPlugin)
    assert plugin in belgie_instance.plugins
    assert plugin.auth == belgie_instance


def test_add_plugin_passes_args(belgie_instance: Belgie) -> None:
    plugin = belgie_instance.add_plugin(MockPlugin, "arg1", kwarg1="value1")
    assert plugin.args == ("arg1",)
    assert plugin.kwargs == {"kwarg1": "value1"}


def test_add_plugin_returns_instance(belgie_instance: Belgie) -> None:
    plugin = belgie_instance.add_plugin(MockPlugin)
    assert isinstance(plugin, MockPlugin)


def test_add_plugin_clears_router_cache(belgie_instance: Belgie) -> None:
    # Access router to cache it
    _ = belgie_instance.router
    assert "router" in belgie_instance.__dict__

    belgie_instance.add_plugin(MockPlugin)
    assert "router" not in belgie_instance.__dict__

    # Access again to rebuild
    _ = belgie_instance.router
    assert "router" in belgie_instance.__dict__
