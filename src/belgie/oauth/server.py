"""OAuth server re-exports for belgie consumers."""

_OAUTH_IMPORT_ERROR = "belgie.oauth.server requires the 'oauth' extra. Install with: uv add belgie[oauth]"

try:
    from belgie_oauth_server import (  # type: ignore[import-not-found]
        OAuthLoginFlowClient,
        OAuthServer,
        OAuthServerLoginContext,
        OAuthServerLoginIntent,
        OAuthServerPlugin,
        build_oauth_metadata,
        build_oauth_metadata_well_known_path,
        build_openid_metadata,
        build_openid_metadata_well_known_path,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_OAUTH_IMPORT_ERROR) from exc

__all__ = [
    "OAuthLoginFlowClient",
    "OAuthServer",
    "OAuthServerLoginContext",
    "OAuthServerLoginIntent",
    "OAuthServerPlugin",
    "build_oauth_metadata",
    "build_oauth_metadata_well_known_path",
    "build_openid_metadata",
    "build_openid_metadata_well_known_path",
]
