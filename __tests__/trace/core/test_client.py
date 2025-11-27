import pytest

from belgie.trace.core.client import TraceClient
from belgie.trace.core.settings import TraceSettings


def test_trace_client_is_frozen() -> None:
    client = TraceClient()

    # Frozen dataclasses should raise FrozenInstanceError on attribute assignment
    with pytest.raises((AttributeError, TypeError)):
        client.settings = TraceSettings(enabled=False)  # type: ignore[misc]


def test_trace_client_initialization_with_defaults() -> None:
    client = TraceClient()

    assert client.db is None
    assert client.adapter is None
    assert isinstance(client.settings, TraceSettings)
    assert client.settings.enabled is True


def test_trace_client_initialization_with_custom_settings() -> None:
    settings = TraceSettings(enabled=False)
    client = TraceClient(settings=settings)

    assert client.settings.enabled is False


def test_trace_client_uses_slots() -> None:
    client = TraceClient()

    # Classes with slots=True don't have __dict__
    assert not hasattr(client, "__dict__")
