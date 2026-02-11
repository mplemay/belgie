from belgie_oauth_server.metadata import (
    build_oauth_metadata,
    build_oauth_metadata_well_known_path,
    build_openid_metadata,
    build_openid_metadata_well_known_path,
    build_protected_resource_metadata,
    build_protected_resource_metadata_well_known_path,
)
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.settings import OAuthResource, OAuthServerSettings

__all__ = [
    "OAuthResource",
    "OAuthServerPlugin",
    "OAuthServerSettings",
    "build_oauth_metadata",
    "build_oauth_metadata_well_known_path",
    "build_openid_metadata",
    "build_openid_metadata_well_known_path",
    "build_protected_resource_metadata",
    "build_protected_resource_metadata_well_known_path",
]
