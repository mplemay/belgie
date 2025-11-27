import belgie


def test_trace_exports() -> None:
    assert hasattr(belgie, "Trace")
    assert hasattr(belgie, "TraceClient")
    assert hasattr(belgie, "TraceSettings")


def test_trace_protocol_exports() -> None:
    assert hasattr(belgie, "TraceAdapterProtocol")


def test_trace_exception_exports() -> None:
    assert hasattr(belgie, "TraceError")


def test_trace_in_all_exports() -> None:
    assert "Trace" in belgie.__all__
    assert "TraceClient" in belgie.__all__
    assert "TraceSettings" in belgie.__all__
    assert "TraceAdapterProtocol" in belgie.__all__
    assert "TraceError" in belgie.__all__


def test_direct_imports() -> None:
    from belgie import Trace, TraceAdapterProtocol, TraceClient, TraceError, TraceSettings  # noqa: PLC0415

    assert Trace is not None
    assert TraceClient is not None
    assert TraceSettings is not None
    assert TraceAdapterProtocol is not None
    assert TraceError is not None


def test_trace_module_imports() -> None:
    from belgie.trace import Trace, TraceAdapterProtocol, TraceClient, TraceError, TraceSettings  # noqa: PLC0415

    assert Trace is not None
    assert TraceClient is not None
    assert TraceSettings is not None
    assert TraceAdapterProtocol is not None
    assert TraceError is not None
