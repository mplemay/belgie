"""Organization alchemy adapter re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = (
    "belgie.alchemy.organization requires the 'alchemy' and 'organization' extras. "
    "Install with: uv add belgie[alchemy,organization]"
)

try:
    from belgie_alchemy.organization import OrganizationAdapter
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = ["OrganizationAdapter"]
