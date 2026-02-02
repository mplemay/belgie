from unittest.mock import Mock

import pytest
from fastapi import APIRouter

from belgie_core.core.belgie import Belgie


class MockSettings:
    pass


class MockPlugin:
    def __init__(self, settings: MockSettings, label: str, *, enabled: bool = True) -> None:
        self.settings = settings
        self.label = label
        self.enabled = enabled

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
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
    db = Mock()
    db.dependency = lambda: None

    return Belgie(settings=settings, adapter=adapter, db=db)


def test_add_plugin_stores_instance(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings, "alpha", enabled=False)
    assert isinstance(plugin, MockPlugin)
    assert plugin in belgie_instance.plugins
    assert plugin.label == "alpha"
    assert plugin.enabled is False
    assert plugin.settings == settings


def test_add_plugin_passes_settings(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings, "alpha")
    assert plugin.settings == settings


def test_add_plugin_returns_instance(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings, "alpha")
    assert isinstance(plugin, MockPlugin)
