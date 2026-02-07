import pytest
from belgie_oauth_server.metadata import (
    _ROOT_RESOURCE_METADATA_PATH,
    build_protected_resource_metadata,
    build_protected_resource_metadata_well_known_path,
)
from belgie_oauth_server.settings import OAuthSettings


def test_build_protected_resource_metadata() -> None:
    settings = OAuthSettings(
        base_url="https://auth.local",
        redirect_uris=["https://app.local/callback"],
        resource_server_url="https://mcp.local/mcp",
        resource_scopes=["user"],
    )

    metadata = build_protected_resource_metadata("https://auth.local/auth/oauth", settings)

    assert str(metadata.resource) == "https://mcp.local/mcp"
    assert [str(value) for value in metadata.authorization_servers] == ["https://auth.local/auth/oauth"]
    assert metadata.scopes_supported == ["user"]


def test_build_protected_resource_metadata_requires_resource_server_url() -> None:
    settings = OAuthSettings(
        base_url="https://auth.local",
        redirect_uris=["https://app.local/callback"],
    )

    with pytest.raises(ValueError, match="resource_server_url"):
        build_protected_resource_metadata("https://auth.local/auth/oauth", settings)


def test_build_protected_resource_metadata_well_known_path_with_path() -> None:
    path = build_protected_resource_metadata_well_known_path("https://mcp.local/mcp")
    assert path == f"{_ROOT_RESOURCE_METADATA_PATH}/mcp"


def test_build_protected_resource_metadata_well_known_path_root() -> None:
    path = build_protected_resource_metadata_well_known_path("https://mcp.local")
    assert path == _ROOT_RESOURCE_METADATA_PATH
