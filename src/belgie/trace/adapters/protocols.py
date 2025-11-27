"""Trace adapter protocols."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


class TraceAdapterProtocol(Protocol):
    """Protocol for trace adapters.

    This is a minimal protocol that will be expanded as tracking features
    are implemented. For now, it only requires the dependency property
    for FastAPI integration.
    """

    @property
    def dependency(self) -> Callable[[], Any]: ...
