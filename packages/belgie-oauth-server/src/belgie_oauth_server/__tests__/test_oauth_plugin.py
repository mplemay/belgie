import pytest
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.engine.errors import InvalidTargetError
from belgie_oauth_server.engine.helpers import resolve_token_resource


def test_resolve_token_resource_accepts_equivalent_trailing_slash() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        test_redirect_uris=["https://client.local/callback"],
        valid_audiences=["http://example.com/mcp/"],
    )

    resolved_resource = resolve_token_resource(
        settings,
        "http://example.com/auth",
        requested_resource="http://example.com/mcp",
    )

    assert resolved_resource == "http://example.com/mcp/"


def test_resolve_token_resource_accepts_requested_and_bound_trailing_slash_mismatch() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        test_redirect_uris=["https://client.local/callback"],
        valid_audiences=["http://example.com/mcp/"],
    )

    resolved_resource = resolve_token_resource(
        settings,
        "http://example.com/auth",
        requested_resource="http://example.com/mcp",
        bound_resource="http://example.com/mcp/",
        require_bound_match=True,
    )

    assert resolved_resource == "http://example.com/mcp/"


def test_resolve_token_resource_rejects_unknown_audience() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        test_redirect_uris=["https://client.local/callback"],
        valid_audiences=["http://example.com/mcp/"],
    )

    with pytest.raises(InvalidTargetError):
        resolve_token_resource(
            settings,
            "http://example.com/auth",
            requested_resource="http://example.com/other",
        )
