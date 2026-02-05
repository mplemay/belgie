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


class BindablePlugin(MockPlugin):
    def __init__(self, settings: MockSettings, label: str, *, enabled: bool = True) -> None:
        super().__init__(settings, label, enabled=enabled)
        self.bound_belgie: Belgie | None = None

    def bind(self, belgie: Belgie) -> None:
        self.bound_belgie = belgie


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


def test_add_plugin_does_not_call_bind_when_missing(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings, "alpha")
    assert not hasattr(plugin, "bound_belgie")


def test_add_plugin_returns_instance(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings, "alpha")
    assert isinstance(plugin, MockPlugin)


def test_add_plugin_calls_optional_bind(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(BindablePlugin, settings, "alpha")
    assert plugin.bound_belgie is belgie_instance
    assert plugin in belgie_instance.plugins


def test_add_plugin_calls_bind_once(belgie_instance: Belgie) -> None:
    class CountedBindablePlugin(MockPlugin):
        def __init__(self, settings: MockSettings, label: str, *, enabled: bool = True) -> None:
            super().__init__(settings, label, enabled=enabled)
            self.bind_calls = 0

        def bind(self, belgie: Belgie) -> None:  # noqa: ARG002
            self.bind_calls += 1

    settings = MockSettings()
    plugin = belgie_instance.add_plugin(CountedBindablePlugin, settings, "alpha")
    assert plugin.bind_calls == 1
