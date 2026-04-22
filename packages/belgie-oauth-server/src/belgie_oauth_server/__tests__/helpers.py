from __future__ import annotations

from typing import Final

from belgie_oauth_server.development import build_development_signing
from belgie_oauth_server.provider import SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.testing import InMemoryDBConnection, InMemoryOAuthServerAdapter
from pydantic import SecretStr

_TEST_DEFAULT_OAUTH_CLIENT_SECRET: Final[str] = "test-secret"  # noqa: S105


def build_oauth_settings(**overrides: object) -> OAuthServer:
    raw_adapter = overrides.pop("adapter", None)
    adapter: InMemoryOAuthServerAdapter
    if raw_adapter is None:
        adapter = InMemoryOAuthServerAdapter()
    elif isinstance(raw_adapter, InMemoryOAuthServerAdapter):
        adapter = raw_adapter
    else:
        msg = "adapter must be InMemoryOAuthServerAdapter for build_oauth_settings in tests"
        raise TypeError(msg)

    test_client_id = str(overrides.pop("test_client_id", "test-client"))
    test_redirect_uris = overrides.pop("test_redirect_uris", None)
    if "test_client_secret" in overrides:
        raw_secret = overrides.pop("test_client_secret")
        if raw_secret is not None and not isinstance(raw_secret, str):
            msg = "test_client_secret must be str or None"
            raise TypeError(msg)
        test_client_secret: str | None = raw_secret
    else:
        test_client_secret = _TEST_DEFAULT_OAUTH_CLIENT_SECRET

    if "static_client_require_pkce" in overrides:
        test_require_pkce = bool(overrides.pop("static_client_require_pkce"))
    elif "test_require_pkce" in overrides:
        test_require_pkce = bool(overrides.pop("test_require_pkce"))
    else:
        test_require_pkce = True

    test_skip_consent = bool(overrides.pop("test_skip_consent", True))
    for forbidden in ("client_id", "redirect_uris", "client_secret"):
        if forbidden in overrides:
            msg = (
                f"Do not pass {forbidden} to build_oauth_settings; use test_client_id, "
                "test_redirect_uris, and test_client_secret instead."
            )
            raise ValueError(msg)
    signing = overrides.pop("signing", build_development_signing())
    fallback = overrides.pop("fallback_signing_secret", SecretStr(_TEST_DEFAULT_OAUTH_CLIENT_SECRET))
    defaults: dict[str, object] = {
        "adapter": adapter,
        "base_url": "http://example.com",
        "login_url": "/login",
        "consent_url": "/consent",
        "signing": signing,
        "fallback_signing_secret": fallback,
    }
    defaults.update(overrides)
    settings = OAuthServer(**defaults)
    uris = list(test_redirect_uris) if test_redirect_uris is not None else None
    adapter.seed_test_client(
        client_id=test_client_id,
        redirect_uris=uris,
        client_secret=test_client_secret,
        require_pkce=test_require_pkce,
        skip_consent=test_skip_consent,
        scope=" ".join(settings.default_scopes),
    )
    return settings


def build_oauth_provider(
    **overrides: object,
) -> tuple[OAuthServer, SimpleOAuthProvider, InMemoryOAuthServerAdapter, InMemoryDBConnection]:
    db = overrides.pop("db", InMemoryDBConnection())
    settings = build_oauth_settings(**overrides)
    adapter = settings.adapter
    if not isinstance(adapter, InMemoryOAuthServerAdapter):
        msg = "build_oauth_provider requires InMemoryOAuthServerAdapter"
        raise TypeError(msg)
    provider = SimpleOAuthProvider(
        settings,
        issuer_url=str(settings.issuer_url),
        database_factory=lambda: db,
    )
    return settings, provider, adapter, db
