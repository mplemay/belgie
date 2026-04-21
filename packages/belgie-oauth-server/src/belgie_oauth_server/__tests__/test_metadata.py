from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.metadata import (
    _ROOT_OAUTH_METADATA_PATH,
    _ROOT_OPENID_METADATA_PATH,
    _ROOT_RESOURCE_METADATA_PATH,
    build_oauth_metadata,
    build_oauth_metadata_well_known_path,
    build_openid_metadata,
    build_openid_metadata_well_known_path,
    build_protected_resource_metadata,
    build_protected_resource_metadata_well_known_path,
)
from belgie_oauth_server.signing import OAuthServerSigning


def test_build_oauth_metadata_supported_grants_and_auth_methods() -> None:
    metadata = build_oauth_metadata(
        "https://auth.local/auth/oauth",
        build_oauth_settings(redirect_uris=["https://client.local/callback"]),
    )

    assert metadata.grant_types_supported == ["authorization_code", "client_credentials", "refresh_token"]
    assert metadata.response_types_supported == ["code"]
    assert metadata.response_modes_supported == ["query"]
    assert metadata.token_endpoint_auth_methods_supported == [
        "client_secret_basic",
        "client_secret_post",
    ]
    assert metadata.introspection_endpoint_auth_methods_supported == ["client_secret_post", "client_secret_basic"]
    assert metadata.revocation_endpoint_auth_methods_supported == ["client_secret_post", "client_secret_basic"]
    assert metadata.authorization_response_iss_parameter_supported is True
    assert str(metadata.jwks_uri) == "https://auth.local/auth/oauth/jwks"


def test_build_oauth_metadata_reflects_configured_server_grants() -> None:
    metadata = build_oauth_metadata(
        "https://auth.local/auth/oauth",
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            grant_types=["client_credentials"],
            login_url=None,
            consent_url=None,
        ),
    )

    assert metadata.grant_types_supported == ["client_credentials"]
    assert metadata.authorization_endpoint is None
    assert metadata.response_types_supported == []


def test_build_oauth_metadata_omits_jwks_uri_for_hs256() -> None:
    metadata = build_oauth_metadata(
        "https://auth.local/auth/oauth",
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            signing=OAuthServerSigning(algorithm="HS256"),
        ),
    )

    assert metadata.jwks_uri is None


def test_build_oauth_metadata_default_hs256_omits_jwks_uri() -> None:
    metadata = build_oauth_metadata(
        "https://auth.local/auth/oauth",
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            signing=OAuthServerSigning(),
        ),
    )

    assert metadata.jwks_uri is None


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


def test_build_protected_resource_metadata_well_known_path_preserves_trailing_slash() -> None:
    path = build_protected_resource_metadata_well_known_path("https://mcp.local/mcp/")
    assert path == f"{_ROOT_RESOURCE_METADATA_PATH}/mcp/"


def test_build_protected_resource_metadata_well_known_path_root() -> None:
    path = build_protected_resource_metadata_well_known_path("https://mcp.local")
    assert path == _ROOT_RESOURCE_METADATA_PATH


def test_build_oauth_metadata_well_known_path_with_path() -> None:
    path = build_oauth_metadata_well_known_path("https://auth.local/auth/oauth")
    assert path == f"{_ROOT_OAUTH_METADATA_PATH}/auth/oauth"


def test_build_oauth_metadata_well_known_path_root() -> None:
    path = build_oauth_metadata_well_known_path("https://auth.local")
    assert path == _ROOT_OAUTH_METADATA_PATH


def test_build_openid_metadata_contains_oidc_endpoints() -> None:
    metadata = build_openid_metadata(
        "https://auth.local/auth/oauth",
        build_oauth_settings(redirect_uris=["https://client.local/callback"]),
    )

    assert str(metadata.userinfo_endpoint) == "https://auth.local/auth/oauth/userinfo"
    assert str(metadata.end_session_endpoint) == "https://auth.local/auth/oauth/end-session"
    assert metadata.id_token_signing_alg_values_supported == ["RS256"]
    assert metadata.subject_types_supported == ["public"]
    assert "sub" in metadata.claims_supported
    assert "openid" in (metadata.scopes_supported or [])
    assert metadata.prompt_values_supported == ["login", "consent", "create", "none"]


def test_build_openid_metadata_default_hs256_advertises_hs256() -> None:
    metadata = build_openid_metadata(
        "https://auth.local/auth/oauth",
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            signing=OAuthServerSigning(),
        ),
    )

    assert metadata.id_token_signing_alg_values_supported == ["HS256"]


def test_build_openid_metadata_advertises_optional_prompt_values_and_pairwise_subjects() -> None:
    metadata = build_openid_metadata(
        "https://auth.local/auth/oauth",
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            login_url="/login",
            consent_url="/consent",
            select_account_url="/select-account",
            pairwise_secret="pairwise-secret-for-tests-123456",
        ),
    )

    assert metadata.prompt_values_supported == ["login", "consent", "create", "none", "select_account"]
    assert metadata.subject_types_supported == ["public", "pairwise"]


def test_build_openid_metadata_well_known_path_with_path() -> None:
    path = build_openid_metadata_well_known_path("https://auth.local/auth/oauth")
    assert path == "/auth/oauth/.well-known/openid-configuration"


def test_build_openid_metadata_well_known_path_root() -> None:
    path = build_openid_metadata_well_known_path("https://auth.local")
    assert path == _ROOT_OPENID_METADATA_PATH
