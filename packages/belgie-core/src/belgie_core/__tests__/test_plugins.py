from dataclasses import dataclass
from unittest.mock import Mock

import pytest
from fastapi import APIRouter

from belgie_core.core.belgie import Belgie


@dataclass(slots=True, kw_only=True, frozen=True)
class MockPluginSettings:
    label: str
    enabled: bool = True


class MockPlugin:
    def __init__(self, belgie_settings: object, settings: MockPluginSettings) -> None:
        self.belgie_settings = belgie_settings
        self.settings = settings
        self.label = settings.label
        self.enabled = settings.enabled

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return APIRouter()

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None


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
    adapter.dependency = lambda: None

    return Belgie(settings=settings, adapter=adapter)


def test_add_plugin_stores_instance(belgie_instance: Belgie) -> None:
    plugin_settings = MockPluginSettings(label="alpha", enabled=False)
    plugin = belgie_instance.add_plugin(MockPlugin, plugin_settings)
    assert isinstance(plugin, MockPlugin)
    assert plugin in belgie_instance.plugins
    assert plugin.label == "alpha"
    assert plugin.enabled is False
    assert plugin.settings == plugin_settings


def test_add_plugin_passes_belgie_settings(belgie_instance: Belgie) -> None:
    plugin_settings = MockPluginSettings(label="alpha")
    plugin = belgie_instance.add_plugin(MockPlugin, plugin_settings)
    assert plugin.belgie_settings is belgie_instance.settings


def test_add_plugin_returns_instance(belgie_instance: Belgie) -> None:
    plugin_settings = MockPluginSettings(label="alpha")
    plugin = belgie_instance.add_plugin(MockPlugin, plugin_settings)
    assert isinstance(plugin, MockPlugin)


def test_add_plugin_legacy_constructor_fails_fast(belgie_instance: Belgie) -> None:
    class LegacyPlugin:
        def __init__(self, settings: MockPluginSettings) -> None:
            self.settings = settings

        def router(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
            return None

        def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
            return None

    plugin_settings = MockPluginSettings(label="alpha")
    with pytest.raises(TypeError, match=r"__init__\(belgie_settings, settings\)"):
        belgie_instance.add_plugin(LegacyPlugin, plugin_settings)
