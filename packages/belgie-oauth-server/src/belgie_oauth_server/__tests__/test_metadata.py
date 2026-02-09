from belgie_oauth_server.metadata import (
    _ROOT_OAUTH_METADATA_PATH,
    _ROOT_RESOURCE_METADATA_PATH,
    build_oauth_metadata_well_known_path,
    build_protected_resource_metadata,
    build_protected_resource_metadata_well_known_path,
)


def test_build_protected_resource_metadata() -> None:
    metadata = build_protected_resource_metadata(
        "https://auth.local/auth/oauth",
        resource_url="https://mcp.local/mcp",
        resource_scopes=["user"],
    )

    assert str(metadata.resource) == "https://mcp.local/mcp"
    assert [str(value) for value in metadata.authorization_servers] == ["https://auth.local/auth/oauth"]
    assert metadata.scopes_supported == ["user"]


def test_build_protected_resource_metadata_well_known_path_with_path() -> None:
    path = build_protected_resource_metadata_well_known_path("https://mcp.local/mcp")
    assert path == f"{_ROOT_RESOURCE_METADATA_PATH}/mcp"


def test_build_protected_resource_metadata_well_known_path_root() -> None:
    path = build_protected_resource_metadata_well_known_path("https://mcp.local")
    assert path == _ROOT_RESOURCE_METADATA_PATH


def test_build_oauth_metadata_well_known_path_with_path() -> None:
    path = build_oauth_metadata_well_known_path("https://auth.local/auth/oauth")
    assert path == f"{_ROOT_OAUTH_METADATA_PATH}/auth/oauth"


def test_build_oauth_metadata_well_known_path_root() -> None:
    path = build_oauth_metadata_well_known_path("https://auth.local")
    assert path == _ROOT_OAUTH_METADATA_PATH
