"""SSO re-exports for belgie consumers."""

_SSO_IMPORT_ERROR = "belgie.sso requires the 'sso' extra. Install with: uv add belgie[sso]"

try:
    from belgie_sso import EnterpriseSSO, SSOClient, SSOPlugin  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    raise ImportError(_SSO_IMPORT_ERROR) from exc

__all__ = [
    "EnterpriseSSO",
    "SSOClient",
    "SSOPlugin",
]
