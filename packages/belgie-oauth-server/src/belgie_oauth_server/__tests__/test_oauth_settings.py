import pytest
from cryptography.hazmat.primitives import serialization
from pydantic import SecretStr, ValidationError

from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.development import DEVELOPMENT_RSA_PRIVATE_KEY_PEM, build_development_signing
from belgie_oauth_server.provider import SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.signing import OAuthServerSigning


def test_oauth_settings_defaults() -> None:
    settings = build_oauth_settings()

    assert settings.login_url == "/login"
    assert settings.signup_url is None
    assert settings.consent_url == "/consent"
    assert settings.select_account_url is None
    assert settings.post_login_url is None
    assert settings.grant_types == ["authorization_code", "client_credentials", "refresh_token"]
    assert settings.default_scopes == ()
    assert settings.pairwise_secret is None
    assert settings.authorization_code_ttl_seconds == 600
    assert settings.access_token_ttl_seconds == 3600
    assert settings.refresh_token_ttl_seconds == 2592000
    assert settings.id_token_ttl_seconds == 36000
    assert settings.state_ttl_seconds == 600
    assert settings.code_challenge_method == "S256"
    assert settings.enable_end_session is False
    assert settings.allow_dynamic_client_registration is False
    assert settings.allow_unauthenticated_client_registration is False
    assert settings.allow_public_client_prelogin is False
    assert settings.valid_audiences is None
    assert settings.request_uri_resolver is None
    assert settings.select_account_resolver is None
    assert settings.post_login_resolver is None
    assert str(settings.issuer_url) == "http://example.com/auth"
    assert settings.resolved_valid_audiences() == ["http://example.com/auth"]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("route_prefix", "/oauth"),
        ("prefix", "/oauth"),
        ("resource_server_url", "http://example.com/mcp"),
        ("resource_scopes", ["user"]),
        ("resources", [{"prefix": "/mcp"}]),
        ("include_root_resource_metadata_fallback", False),
        ("include_root_oauth_metadata_fallback", False),
        ("include_root_openid_metadata_fallback", False),
    ],
)
def test_oauth_settings_rejects_removed_legacy_fields(field_name: str, value: object) -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServer(
            adapter=build_oauth_settings().adapter,
            base_url="http://example.com",
            login_url="/login",
            consent_url="/consent",
            signing=build_development_signing(),
            **{field_name: value},
        )

    assert field_name in str(exc.value)


def test_oauth_settings_accepts_valid_audiences_and_deduplicates_supported_scopes() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        default_scopes=["user", "profile"],
        client_registration_allowed_scopes=["profile", "email"],
        valid_audiences=["http://example.com/mcp/", "http://example.com/mcp/"],
    )

    assert [str(value) for value in settings.valid_audiences or []] == [
        "http://example.com/mcp/",
        "http://example.com/mcp/",
    ]
    assert settings.resolved_valid_audiences() == ["http://example.com/mcp/"]
    assert settings.supported_scopes() == ["user", "profile", "openid", "email", "offline_access"]


def test_oauth_settings_accepts_advertised_metadata_subset() -> None:
    settings = build_oauth_settings(
        default_scopes=["user", "files:read"],
        advertised_metadata={
            "scopes_supported": ["user", "openid"],
            "claims_supported": ["sub", "tenant"],
        },
    )

    assert settings.advertised_metadata is not None
    assert settings.advertised_metadata.scopes_supported == ["user", "openid"]
    assert settings.advertised_metadata.claims_supported == ["sub", "tenant"]


def test_oauth_settings_rejects_invalid_advertised_scope() -> None:
    with pytest.raises(ValidationError) as exc:
        build_oauth_settings(
            default_scopes=["user"],
            advertised_metadata={
                "scopes_supported": ["admin"],
            },
        )

    assert "advertised_metadata.scopes_supported admin not found in supported scopes" in str(exc.value)


def test_oauth_settings_resolves_valid_audiences_from_fallback_issuer() -> None:
    settings = OAuthServer(
        adapter=build_oauth_settings().adapter,
        login_url="/login",
        consent_url="/consent",
        base_url=None,
    )

    assert settings.issuer_url is None
    assert settings.resolved_valid_audiences("http://fallback.local/auth") == ["http://fallback.local/auth"]


def test_oauth_settings_accepts_signup_url() -> None:
    settings = build_oauth_settings(
        signup_url="/signup",
    )

    assert settings.signup_url == "/signup"


def test_oauth_settings_rejects_missing_login_url_when_authorization_code_enabled() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServer(
            adapter=build_oauth_settings().adapter,
            base_url="http://example.com",
            consent_url="/consent",
            signing=build_development_signing(),
        )

    assert "login_url is required when authorization_code grant is enabled" in str(exc.value)


def test_oauth_settings_rejects_missing_consent_url_when_authorization_code_enabled() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServer(
            adapter=build_oauth_settings().adapter,
            base_url="http://example.com",
            login_url="/login",
            signing=build_development_signing(),
        )

    assert "consent_url is required when authorization_code grant is enabled" in str(exc.value)


def test_oauth_settings_rejects_short_pairwise_secret() -> None:
    with pytest.raises(ValidationError) as exc:
        build_oauth_settings(pairwise_secret=SecretStr("too-short"))

    assert "pairwise_secret must be at least 32 characters" in str(exc.value)


def test_oauth_settings_rejects_refresh_token_without_authorization_code() -> None:
    with pytest.raises(ValidationError) as exc:
        build_oauth_settings(
            grant_types=["client_credentials", "refresh_token"],
            login_url=None,
            consent_url=None,
        )

    assert "refresh_token grant requires authorization_code grant" in str(exc.value)


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
        login_url="/login",
        consent_url="/consent",
    )

    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    assert provider.signing_state.algorithm == "HS256"
    assert provider.signing_state.jwks is None


def test_oauth_settings_explicit_rs256_accepts_private_key() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
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
        signing=OAuthServerSigning(
            algorithm="RS256",
            private_key_pem=SecretStr(DEVELOPMENT_RSA_PRIVATE_KEY_PEM),
            public_key_pem=SecretStr(public_pem.decode("utf-8")),
        ),
    )

    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    assert provider.signing_state.verification_key == public_pem
