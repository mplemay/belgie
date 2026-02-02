from unittest.mock import Mock

import pytest
from fastapi import APIRouter

from belgie_core.core.belgie import Belgie


class MockSettings:
    pass


class MockPlugin:
    def __init__(self, belgie: Belgie, settings: MockSettings) -> None:
        self.belgie = belgie
        self.settings = settings

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
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings)
    assert isinstance(plugin, MockPlugin)
    assert plugin in belgie_instance.plugins
    assert plugin.belgie == belgie_instance


def test_add_plugin_passes_settings(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings)
    assert plugin.settings == settings


def test_add_plugin_returns_instance(belgie_instance: Belgie) -> None:
    settings = MockSettings()
    plugin = belgie_instance.add_plugin(MockPlugin, settings)
    assert isinstance(plugin, MockPlugin)
