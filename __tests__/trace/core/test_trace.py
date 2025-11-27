from unittest.mock import Mock

from belgie.trace.core.client import TraceClient
from belgie.trace.core.settings import TraceSettings
from belgie.trace.core.trace import Trace, _TraceCallable


def test_trace_initialization() -> None:
    trace = Trace()

    assert trace.adapter is None
    assert isinstance(trace.settings, TraceSettings)
    assert trace.settings.enabled is True


def test_trace_initialization_with_settings() -> None:
    settings = TraceSettings(enabled=False)
    trace = Trace(settings=settings)

    assert trace.settings.enabled is False


def test_trace_initialization_with_adapter() -> None:
    mock_adapter = Mock()
    mock_adapter.dependency = Mock()

    trace = Trace(adapter=mock_adapter)

    assert trace.adapter is mock_adapter


def test_trace_has_callable_descriptor() -> None:
    assert isinstance(Trace.__call__, _TraceCallable)


def test_descriptor_returns_self_when_accessed_on_class() -> None:
    descriptor = Trace.__call__

    # When accessed on class (not instance), should return descriptor itself
    result = descriptor.__get__(None, Trace)

    assert result is descriptor


def test_descriptor_returns_callable_when_accessed_on_instance() -> None:
    trace = Trace()
    descriptor = Trace.__call__

    # When accessed on instance, should return a callable
    result = descriptor.__get__(trace, Trace)

    assert callable(result)


def test_trace_callable_returns_trace_client() -> None:
    mock_adapter = Mock()
    mock_dependency = Mock(return_value=None)
    mock_adapter.dependency = mock_dependency

    settings = TraceSettings(enabled=False)
    trace = Trace(adapter=mock_adapter, settings=settings)

    # Get the callable
    trace_callable = trace.__call__.__get__(trace, Trace)  # type: ignore[attr-defined]

    # Call it - uses default db from Depends()
    client = trace_callable()

    assert isinstance(client, TraceClient)
    assert client.adapter is mock_adapter
    assert client.settings.enabled is False


def test_trace_callable_without_adapter() -> None:
    trace = Trace()

    # Get the callable
    trace_callable = trace.__call__.__get__(trace, Trace)  # type: ignore[attr-defined]

    # Call it - uses default db (None when no adapter)
    client = trace_callable()

    assert isinstance(client, TraceClient)
    assert client.adapter is None
