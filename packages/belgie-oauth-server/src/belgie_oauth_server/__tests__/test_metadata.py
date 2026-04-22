import pytest
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.metadata import (
    _ROOT_OAUTH_METADATA_PATH,
    _ROOT_OPENID_METADATA_PATH,
    build_oauth_metadata,
    build_oauth_metadata_well_known_path,
    build_openid_metadata,
    build_openid_metadata_well_known_path,
    build_protected_resource_metadata,
)
from belgie_oauth_server.signing import OAuthServerSigning

ISSUER_URL = "https://auth.local/auth"


def test_build_oauth_metadata_supported_grants_and_auth_methods() -> None:
    metadata = build_oauth_metadata(
        ISSUER_URL,
        build_oauth_settings(redirect_uris=["https://client.local/callback"]),
    )

    assert str(metadata.authorization_endpoint) == f"{ISSUER_URL}/oauth2/authorize"
    assert str(metadata.token_endpoint) == f"{ISSUER_URL}/oauth2/token"
    assert str(metadata.registration_endpoint) == f"{ISSUER_URL}/oauth2/register"
    assert str(metadata.introspection_endpoint) == f"{ISSUER_URL}/oauth2/introspect"
    assert str(metadata.revocation_endpoint) == f"{ISSUER_URL}/oauth2/revoke"
    assert metadata.grant_types_supported == ["authorization_code", "client_credentials", "refresh_token"]
    assert metadata.response_types_supported == ["code"]
    assert metadata.response_modes_supported == ["query"]
    assert metadata.token_endpoint_auth_methods_supported == [
        "client_secret_basic",
        "client_secret_post",
    ]
    assert metadata.introspection_endpoint_auth_methods_supported == [
        "client_secret_basic",
        "client_secret_post",
    ]
    assert metadata.revocation_endpoint_auth_methods_supported == [
        "client_secret_basic",
        "client_secret_post",
    ]
    assert metadata.authorization_response_iss_parameter_supported is True
    assert str(metadata.jwks_uri) == f"{ISSUER_URL}/jwks"


def test_build_oauth_metadata_advertises_public_clients_only_when_unauthenticated_registration_is_enabled() -> None:
    metadata = build_oauth_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            allow_unauthenticated_client_registration=True,
        ),
    )

    assert metadata.token_endpoint_auth_methods_supported == [
        "none",
        "client_secret_basic",
        "client_secret_post",
    ]


def test_build_oauth_metadata_uses_advertised_scopes_supported() -> None:
    metadata = build_oauth_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            default_scopes=["user", "files:read"],
            advertised_metadata={
                "scopes_supported": ["user", "openid"],
            },
        ),
    )

    assert metadata.scopes_supported == ["user", "openid"]


def test_build_oauth_metadata_reflects_configured_server_grants() -> None:
    metadata = build_oauth_metadata(
        ISSUER_URL,
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
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            signing=OAuthServerSigning(algorithm="HS256"),
        ),
    )

    assert metadata.jwks_uri is None


def test_build_oauth_metadata_default_hs256_omits_jwks_uri() -> None:
    metadata = build_oauth_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            signing=OAuthServerSigning(),
        ),
    )

    assert metadata.jwks_uri is None


def test_build_oauth_metadata_omits_jwks_uri_when_jwt_plugin_is_disabled() -> None:
    metadata = build_oauth_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            disable_jwt_plugin=True,
        ),
    )

    assert metadata.jwks_uri is None


def test_build_oauth_metadata_well_known_path_with_path() -> None:
    path = build_oauth_metadata_well_known_path(ISSUER_URL)
    assert path == f"{_ROOT_OAUTH_METADATA_PATH}/auth"


def test_build_oauth_metadata_well_known_path_root() -> None:
    path = build_oauth_metadata_well_known_path("https://auth.local")
    assert path == _ROOT_OAUTH_METADATA_PATH


def test_build_openid_metadata_contains_oidc_endpoints() -> None:
    metadata = build_openid_metadata(
        ISSUER_URL,
        build_oauth_settings(redirect_uris=["https://client.local/callback"]),
    )

    assert str(metadata.userinfo_endpoint) == f"{ISSUER_URL}/oauth2/userinfo"
    assert str(metadata.end_session_endpoint) == f"{ISSUER_URL}/oauth2/end-session"
    assert metadata.id_token_signing_alg_values_supported == ["RS256"]
    assert metadata.token_endpoint_auth_methods_supported == [
        "client_secret_basic",
        "client_secret_post",
    ]
    assert metadata.subject_types_supported == ["public"]
    assert "sub" in metadata.claims_supported
    assert "openid" in (metadata.scopes_supported or [])
    assert metadata.prompt_values_supported == ["login", "consent", "create", "select_account", "none"]


def test_build_openid_metadata_default_hs256_advertises_hs256() -> None:
    metadata = build_openid_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            signing=OAuthServerSigning(),
        ),
    )

    assert metadata.id_token_signing_alg_values_supported == ["HS256"]


def test_build_openid_metadata_disable_jwt_plugin_advertises_hs256() -> None:
    metadata = build_openid_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            disable_jwt_plugin=True,
        ),
    )

    assert metadata.id_token_signing_alg_values_supported == ["HS256"]
    assert metadata.jwks_uri is None


def test_build_openid_metadata_advertises_pairwise_subjects() -> None:
    metadata = build_openid_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            pairwise_secret="pairwise-secret-for-tests-123456",
        ),
    )

    assert metadata.subject_types_supported == ["public", "pairwise"]


def test_build_openid_metadata_uses_advertised_claims_supported() -> None:
    metadata = build_openid_metadata(
        ISSUER_URL,
        build_oauth_settings(
            redirect_uris=["https://client.local/callback"],
            advertised_metadata={
                "claims_supported": ["sub", "tenant"],
            },
        ),
    )

    assert metadata.claims_supported == ["sub", "tenant"]


def test_build_openid_metadata_well_known_path_with_path() -> None:
    path = build_openid_metadata_well_known_path(ISSUER_URL)
    assert path == "/auth/.well-known/openid-configuration"


def test_build_openid_metadata_well_known_path_root() -> None:
    path = build_openid_metadata_well_known_path("https://auth.local")
    assert path == _ROOT_OPENID_METADATA_PATH


def test_build_protected_resource_metadata_defaults_authorization_server() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
        default_scopes=["user"],
    )

    metadata = build_protected_resource_metadata(
        "https://mcp.local/mcp",
        settings=settings,
        scopes_supported=["user"],
    )

    assert str(metadata.resource) == "https://mcp.local/mcp"
    assert [str(value) for value in metadata.authorization_servers] == ["https://auth.local/auth"]
    assert metadata.scopes_supported == ["user"]


def test_build_protected_resource_metadata_allows_overriding_authorization_servers() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
        default_scopes=["user"],
    )

    metadata = build_protected_resource_metadata(
        "https://mcp.local/mcp",
        settings=settings,
        authorization_servers=["https://auth.local/auth", "https://admin.local/auth"],
        scopes_supported=["user"],
    )

    assert [str(value) for value in metadata.authorization_servers] == [
        "https://auth.local/auth",
        "https://admin.local/auth",
    ]
    assert metadata.scopes_supported == ["user"]


def test_build_protected_resource_metadata_rejects_openid_scope() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
        default_scopes=["user"],
    )

    with pytest.raises(ValueError, match="openid"):
        build_protected_resource_metadata(
            "https://mcp.local/mcp",
            settings=settings,
            scopes_supported=["openid"],
        )


def test_build_protected_resource_metadata_warns_for_oidc_style_scopes() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
    )

    with pytest.warns(UserWarning, match="typically restricted"):
        metadata = build_protected_resource_metadata(
            "https://mcp.local/mcp",
            settings=settings,
            scopes_supported=["profile"],
        )

    assert metadata.scopes_supported == ["profile"]


def test_build_protected_resource_metadata_silences_oidc_scope_warnings() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
    )

    metadata = build_protected_resource_metadata(
        "https://mcp.local/mcp",
        settings=settings,
        scopes_supported=["profile"],
        silence_oidc_scope_warnings=True,
    )

    assert metadata.scopes_supported == ["profile"]


def test_build_protected_resource_metadata_rejects_unsupported_scope() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
        default_scopes=["user"],
    )

    with pytest.raises(ValueError, match='Unsupported scope "write:posts"'):
        build_protected_resource_metadata(
            "https://mcp.local/mcp",
            settings=settings,
            scopes_supported=["write:posts"],
        )


def test_build_protected_resource_metadata_rejects_external_scopes_with_one_authorization_server() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
        default_scopes=["read:posts"],
    )

    with pytest.raises(ValueError, match="external scopes should not be provided with one authorization server"):
        build_protected_resource_metadata(
            "https://mcp.local/mcp",
            settings=settings,
            authorization_servers=["https://auth.local/auth"],
            scopes_supported=["read:posts", "write:posts"],
            external_scopes=["write:posts"],
        )


def test_build_protected_resource_metadata_allows_external_scopes_with_multiple_authorization_servers() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["https://client.local/callback"],
        default_scopes=["read:posts"],
    )

    metadata = build_protected_resource_metadata(
        "https://mcp.local/mcp",
        settings=settings,
        authorization_servers=["https://auth.local/auth", "https://partner.local/auth"],
        scopes_supported=["read:posts", "write:posts"],
        external_scopes=["write:posts"],
    )

    assert [str(value) for value in metadata.authorization_servers] == [
        "https://auth.local/auth",
        "https://partner.local/auth",
    ]
    assert metadata.scopes_supported == ["read:posts", "write:posts"]
