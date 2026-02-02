"""OAuth re-exports for belgie consumers."""

_OAUTH_IMPORT_ERROR = "belgie.oauth requires the 'oauth' extra. Install with: uv add belgie[oauth]"

try:
    from belgie_oauth import hello  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    raise ImportError(_OAUTH_IMPORT_ERROR) from exc

__all__ = [
    "hello",
]
