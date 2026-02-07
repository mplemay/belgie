"""OAuth re-exports for belgie consumers."""

_OAUTH_IMPORT_ERROR = "belgie.oauth requires the 'oauth' extra. Install with: uv add belgie[oauth]"

try:
    from belgie_oauth_server import (  # type: ignore[import-not-found]
        OAuthPlugin,
        OAuthSettings,
        build_oauth_metadata,
        build_oauth_metadata_well_known_path,
        build_protected_resource_metadata,
        build_protected_resource_metadata_well_known_path,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_OAUTH_IMPORT_ERROR) from exc

__all__ = [
    "OAuthPlugin",
    "OAuthSettings",
    "build_oauth_metadata",
    "build_oauth_metadata_well_known_path",
    "build_protected_resource_metadata",
    "build_protected_resource_metadata_well_known_path",
]
