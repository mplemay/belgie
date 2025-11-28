from unittest.mock import Mock

from belgie.trace.adapters.protocols import TraceAdapterProtocol


def test_mock_adapter_satisfies_protocol() -> None:
    mock_adapter = Mock(spec=TraceAdapterProtocol)
    assert isinstance(mock_adapter, TraceAdapterProtocol)


def test_adapter_protocol_runtime_check() -> None:
    class TestAdapter:
        pass

    adapter = TestAdapter()
    assert isinstance(adapter, TraceAdapterProtocol)
