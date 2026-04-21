from __future__ import annotations

from belgie_oauth_server.development import build_development_signing
from belgie_oauth_server.provider import SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.testing import InMemoryDBConnection, InMemoryOAuthServerAdapter


def build_oauth_settings(**overrides: object) -> OAuthServer:
    defaults: dict[str, object] = {
        "adapter": overrides.pop("adapter", InMemoryOAuthServerAdapter()),
        "redirect_uris": ["http://example.com/callback"],
        "base_url": "http://example.com",
        "client_id": "test-client",
        "signing": overrides.pop("signing", build_development_signing()),
    }
    defaults.update(overrides)
    return OAuthServer(**defaults)


def build_oauth_provider(
    **overrides: object,
) -> tuple[OAuthServer, SimpleOAuthProvider, InMemoryOAuthServerAdapter, InMemoryDBConnection]:
    adapter = overrides.pop("adapter", InMemoryOAuthServerAdapter())
    db = overrides.pop("db", InMemoryDBConnection())
    settings = build_oauth_settings(adapter=adapter, **overrides)
    provider = SimpleOAuthProvider(
        settings,
        issuer_url=str(settings.issuer_url),
        database_factory=lambda: db,
    )
    return settings, provider, adapter, db
