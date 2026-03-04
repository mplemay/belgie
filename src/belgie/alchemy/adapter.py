"""Adapter re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy.adapter requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy import BelgieAdapter, OrganizationAdapter, TeamAdapter  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = ["BelgieAdapter", "OrganizationAdapter", "TeamAdapter"]
