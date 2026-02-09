"""Google OAuth re-exports for belgie consumers."""

_OAUTH_CLIENT_IMPORT_ERROR = (
    "belgie.oauth.google requires the 'oauth-client' extra. Install with: uv add belgie[oauth-client]"
)

try:
    from belgie_oauth import (  # type: ignore[import-not-found]
        GoogleOAuthClient,
        GoogleOAuthPlugin,
        GoogleOAuthSettings,
        GoogleUserInfo,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_OAUTH_CLIENT_IMPORT_ERROR) from exc

__all__ = [
    "GoogleOAuthClient",
    "GoogleOAuthPlugin",
    "GoogleOAuthSettings",
    "GoogleUserInfo",
]
