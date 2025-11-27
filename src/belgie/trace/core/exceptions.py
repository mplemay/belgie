"""Trace module exceptions."""

from belgie.auth.core.exceptions import BelgieError


class TraceError(BelgieError):
    """Base exception for trace module."""
