"""Alchemy re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy import (  # type: ignore[import-not-found]
        AlchemyAdapter,
        Base,
        DatabaseSettings,
        DateTimeUTC,
        PrimaryKeyMixin,
        TimestampMixin,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "AlchemyAdapter",
    "Base",
    "DatabaseSettings",
    "DateTimeUTC",
    "PrimaryKeyMixin",
    "TimestampMixin",
]
