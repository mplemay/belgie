"""Trace analytics module for Belgie.

This module provides basic infrastructure for analytics and tracking functionality.
Full tracking features will be added incrementally.
"""

from belgie.trace.adapters.protocols import TraceAdapterProtocol
from belgie.trace.core.client import TraceClient
from belgie.trace.core.exceptions import TraceError
from belgie.trace.core.settings import TraceSettings
from belgie.trace.core.trace import Trace

__all__ = [
    "Trace",
    "TraceAdapterProtocol",
    "TraceClient",
    "TraceError",
    "TraceSettings",
]
