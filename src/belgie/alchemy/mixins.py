"""Mixin re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy.mixins requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy import (  # type: ignore[import-not-found]
        AccountMixin,
        OAuthStateMixin,
        SessionMixin,
        UserMixin,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "AccountMixin",
    "OAuthStateMixin",
    "SessionMixin",
    "UserMixin",
]
