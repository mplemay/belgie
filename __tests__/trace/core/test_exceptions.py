import pytest

from belgie.auth.core.exceptions import BelgieError
from belgie.trace.core.exceptions import TraceError


def test_trace_error_is_belgie_error() -> None:
    assert issubclass(TraceError, BelgieError)


def test_trace_error_is_exception() -> None:
    assert issubclass(TraceError, Exception)


def test_can_raise_and_catch_trace_error() -> None:
    msg = "test trace error"
    with pytest.raises(TraceError, match=msg):
        raise TraceError(msg)


def test_can_catch_trace_error_as_belgie_error() -> None:
    msg = "trace error message"
    with pytest.raises(BelgieError):
        raise TraceError(msg)
