from unittest.mock import Mock

from belgie.trace.adapters.protocols import TraceAdapterProtocol


def test_mock_adapter_satisfies_protocol() -> None:
    mock_adapter = Mock(spec=TraceAdapterProtocol)
    mock_adapter.dependency = Mock()

    # Protocol check - should have dependency property
    assert hasattr(mock_adapter, "dependency")
    assert callable(mock_adapter.dependency) or isinstance(mock_adapter.dependency, property)


def test_adapter_protocol_requires_dependency_property() -> None:
    # Create a class that implements the protocol
    class TestAdapter:
        @property
        def dependency(self):
            return lambda: None

    adapter = TestAdapter()

    # Should satisfy protocol
    assert isinstance(adapter, TraceAdapterProtocol)
