from dataclasses import dataclass
from unittest.mock import Mock

import pytest
from fastapi import APIRouter

from belgie_core.core.belgie import Belgie


@dataclass(slots=True, kw_only=True, frozen=True)
class MockPluginConfig:
    label: str
    enabled: bool = True

    def __call__(self, belgie_settings: object) -> "MockPlugin":
        return MockPlugin(belgie_settings, self)


class MockPlugin:
    def __init__(self, belgie_settings: object, settings: MockPluginConfig) -> None:
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
    database = Mock()
    database.dependency = lambda: None

    return Belgie(settings=settings, adapter=adapter, database=database)


def test_add_plugin_stores_instance(belgie_instance: Belgie) -> None:
    plugin_config = MockPluginConfig(label="alpha", enabled=False)
    plugin = belgie_instance.add_plugin(plugin_config)
    assert isinstance(plugin, MockPlugin)
    assert plugin in belgie_instance.plugins
    assert plugin.label == "alpha"
    assert plugin.enabled is False
    assert plugin.settings == plugin_config


def test_add_plugin_passes_belgie_settings(belgie_instance: Belgie) -> None:
    plugin_config = MockPluginConfig(label="alpha")
    plugin = belgie_instance.add_plugin(plugin_config)
    assert plugin.belgie_settings is belgie_instance.settings


def test_add_plugin_returns_instance(belgie_instance: Belgie) -> None:
    plugin_config = MockPluginConfig(label="alpha")
    plugin = belgie_instance.add_plugin(plugin_config)
    assert isinstance(plugin, MockPlugin)


def test_add_plugin_callable_signature_fails_fast(belgie_instance: Belgie) -> None:
    class LegacyPluginConfig:
        def __call__(self) -> MockPlugin:
            return MockPlugin(belgie_instance.settings, MockPluginConfig(label="alpha"))

    with pytest.raises(TypeError, match=r"__call__\(belgie_settings\)"):
        belgie_instance.add_plugin(LegacyPluginConfig())


def test_add_plugin_return_type_fails_fast(belgie_instance: Belgie) -> None:
    class InvalidPluginConfig:
        def __call__(self, belgie_settings: object) -> object:  # noqa: ARG002
            return object()

    with pytest.raises(TypeError, match=r"must return an object implementing"):
        belgie_instance.add_plugin(InvalidPluginConfig())
