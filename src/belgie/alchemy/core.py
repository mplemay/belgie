"""Core alchemy adapter re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy.core requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy.core import BelgieAdapter
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = ["BelgieAdapter"]
