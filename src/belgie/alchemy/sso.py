"""SSO alchemy adapter re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = (
    "belgie.alchemy.sso requires the 'alchemy' and 'sso' extras. Install with: uv add belgie[alchemy,sso]"
)

try:
    from belgie_alchemy.sso import SSOAdapter, SSODomainMixin, SSOProviderMixin
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "SSOAdapter",
    "SSODomainMixin",
    "SSOProviderMixin",
]
