_OAUTH_CLIENT_IMPORT_ERROR = (
    "belgie.oauth.microsoft requires the 'oauth-client' extra. Install with: uv add belgie[oauth-client]"
)

try:
    from belgie_oauth import (  # type: ignore[import-not-found]
        MicrosoftOAuth,
        MicrosoftOAuthClient,
        MicrosoftOAuthPlugin,
        MicrosoftUserInfo,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_OAUTH_CLIENT_IMPORT_ERROR) from exc

__all__ = [
    "MicrosoftOAuth",
    "MicrosoftOAuthClient",
    "MicrosoftOAuthPlugin",
    "MicrosoftUserInfo",
]
