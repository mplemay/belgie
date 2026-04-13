"""OAuth server alchemy re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy.oauth_server requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy.oauth_server import (
        OAuthServerAccessTokenMixin,
        OAuthServerAdapter,
        OAuthServerAuthorizationCodeMixin,
        OAuthServerAuthorizationStateMixin,
        OAuthServerClientMixin,
        OAuthServerConsentMixin,
        OAuthServerRefreshTokenMixin,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "OAuthServerAccessTokenMixin",
    "OAuthServerAdapter",
    "OAuthServerAuthorizationCodeMixin",
    "OAuthServerAuthorizationStateMixin",
    "OAuthServerClientMixin",
    "OAuthServerConsentMixin",
    "OAuthServerRefreshTokenMixin",
]
