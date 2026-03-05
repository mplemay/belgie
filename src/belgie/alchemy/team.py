"""Team alchemy adapter re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = (
    "belgie.alchemy.team requires the 'alchemy' and 'team' extras. Install with: uv add belgie[alchemy,team]"
)

try:
    from belgie_alchemy.team import TeamAdapter
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = ["TeamAdapter"]
