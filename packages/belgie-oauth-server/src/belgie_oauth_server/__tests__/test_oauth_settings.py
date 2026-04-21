import pytest
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.development import DEVELOPMENT_RSA_PRIVATE_KEY_PEM, build_development_signing
from belgie_oauth_server.provider import SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer, OAuthServerResource
from belgie_oauth_server.signing import OAuthServerSigning
from cryptography.hazmat.primitives import serialization
from pydantic import SecretStr, ValidationError


def test_oauth_settings_defaults() -> None:
    settings = build_oauth_settings(redirect_uris=["http://example.com/callback"])

    assert settings.prefix == "/oauth"
    assert settings.login_url is None
    assert settings.signup_url is None
    assert settings.consent_url is None
    assert settings.select_account_url is None
    assert settings.default_scope == "user"
    assert settings.static_client_require_pkce is True
    assert settings.pairwise_secret is None
    assert settings.authorization_code_ttl_seconds == 300
    assert settings.access_token_ttl_seconds == 3600
    assert settings.refresh_token_ttl_seconds == 2592000
    assert settings.id_token_ttl_seconds == 36000
    assert settings.state_ttl_seconds == 600
    assert settings.code_challenge_method == "S256"
    assert settings.enable_end_session is False
    assert settings.allow_dynamic_client_registration is False
    assert settings.allow_unauthenticated_client_registration is False
    assert settings.resources is None
    assert settings.include_root_resource_metadata_fallback is True
    assert settings.request_uri_resolver is None
    assert settings.select_account_resolver is None
    assert settings.include_root_openid_metadata_fallback is True


def test_oauth_settings_requires_redirect_uris() -> None:
    with pytest.raises(ValidationError) as exc:
        build_oauth_settings(redirect_uris=None)
    assert "redirect_uris" in str(exc.value)


def test_oauth_settings_rejects_empty_redirect_uris() -> None:
    with pytest.raises(ValidationError) as exc:
        build_oauth_settings(redirect_uris=[])
    assert "redirect_uris" in str(exc.value)


def test_oauth_settings_rejects_legacy_route_prefix() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServer(
            adapter=build_oauth_settings().adapter,
            redirect_uris=["http://example.com/callback"],
            signing=build_development_signing(),
            route_prefix="/oauth",
        )
    assert "route_prefix" in str(exc.value)


def test_oauth_settings_rejects_legacy_resource_settings() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServer(
            adapter=build_oauth_settings().adapter,
            redirect_uris=["http://example.com/callback"],
            signing=build_development_signing(),
            resource_server_url="http://example.com/mcp",
        )
    assert "resource_server_url" in str(exc.value)


def test_oauth_settings_rejects_legacy_resource_scopes() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServer(
            adapter=build_oauth_settings().adapter,
            redirect_uris=["http://example.com/callback"],
            signing=build_development_signing(),
            resource_scopes=["user"],
        )
    assert "resource_scopes" in str(exc.value)


def test_oauth_settings_populates_issuer_url_from_base_url() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
    )

    assert str(settings.issuer_url) == "http://example.com/auth/oauth"


def test_oauth_settings_accepts_resource_metadata_settings() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
        resources=[OAuthServerResource(prefix="/mcp", scopes=["user", "files:read"])],
        include_root_resource_metadata_fallback=False,
    )

    assert settings.resources is not None
    assert settings.resources[0].prefix == "/mcp"
    assert settings.resources[0].scopes == ["user", "files:read"]
    assert settings.include_root_resource_metadata_fallback is False

    resource_url, resource_scopes = settings.resolve_resource()
    assert str(resource_url) == "http://example.com/mcp"
    assert resource_scopes == ["user", "files:read"]


def test_oauth_settings_preserves_resource_trailing_slash() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
        resources=[OAuthServerResource(prefix="/mcp/", scopes=["user"])],
    )

    resource_url, resource_scopes = settings.resolve_resource()
    assert str(resource_url) == "http://example.com/mcp/"
    assert resource_scopes == ["user"]


def test_oauth_settings_accepts_signup_url() -> None:
    settings = build_oauth_settings(
        redirect_uris=["http://example.com/callback"],
        signup_url="/signup",
    )

    assert settings.signup_url == "/signup"


def test_oauth_settings_rejects_multiple_resources() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServer(
            adapter=build_oauth_settings().adapter,
            redirect_uris=["http://example.com/callback"],
            signing=build_development_signing(),
            resources=[OAuthServerResource(prefix="/mcp"), OAuthServerResource(prefix="/files")],
        )
    assert "resources" in str(exc.value)


def test_oauth_settings_rejects_refresh_token_encoder_without_decoder() -> None:
    with pytest.raises(ValidationError) as exc:
        build_oauth_settings(
            refresh_token_encoder=lambda token, session_id: f"wrapped:{session_id}:{token}",
        )

    assert "refresh_token_decoder" in str(exc.value)


def test_oauth_settings_allows_refresh_token_decoder_without_encoder() -> None:
    settings = build_oauth_settings(
        refresh_token_decoder=lambda token: (None, token),
    )

    assert settings.refresh_token_decoder is not None


def test_oauth_settings_default_hs256_initializes_without_private_key() -> None:
    settings = OAuthServer(
        adapter=build_oauth_settings().adapter,
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
    )

    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    assert provider.signing_state.algorithm == "HS256"
    assert provider.signing_state.jwks is None


def test_oauth_settings_explicit_rs256_accepts_private_key() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
        signing=build_development_signing(),
    )

    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    assert provider.signing_state.algorithm == "RS256"
    assert provider.signing_state.jwks is not None


def test_oauth_settings_rs256_accepts_explicit_public_key() -> None:
    private_key = serialization.load_pem_private_key(
        DEVELOPMENT_RSA_PRIVATE_KEY_PEM.encode("utf-8"),
        password=None,
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings = build_oauth_settings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
        signing=OAuthServerSigning(
            algorithm="RS256",
            private_key_pem=SecretStr(DEVELOPMENT_RSA_PRIVATE_KEY_PEM),
            public_key_pem=SecretStr(public_pem.decode("utf-8")),
        ),
    )

    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    assert provider.signing_state.verification_key == public_pem


def test_oauth_settings_resolves_resource_with_fallback_base_url() -> None:
    settings = build_oauth_settings(
        redirect_uris=["http://example.com/callback"],
        resources=[OAuthServerResource(prefix="/mcp", scopes=["user"])],
    )

    resource_url, resource_scopes = settings.resolve_resource("http://example.com")
    assert str(resource_url) == "http://example.com/mcp"
    assert resource_scopes == ["user"]
