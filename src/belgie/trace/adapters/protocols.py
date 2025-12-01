"""Trace adapter protocols."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TraceAdapterProtocol(Protocol):
    """Protocol for trace adapters.

    This is a minimal protocol that will be expanded as tracking features
    are implemented.
    """
