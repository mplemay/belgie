from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.plugin import _resolve_token_resource, _validate_authorize_resource
from belgie_oauth_server.settings import OAuthResource


def test_validate_authorize_resource_accepts_equivalent_trailing_slash() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        redirect_uris=["http://client.local/callback"],
        resources=[OAuthResource(prefix="/mcp/", scopes=["user"])],
    )

    resolved_resource = _validate_authorize_resource(
        settings,
        "http://example.com",
        "http://example.com/mcp",
    )

    assert resolved_resource == "http://example.com/mcp/"


def test_resolve_token_resource_accepts_requested_and_bound_trailing_slash_mismatch() -> None:
    settings = build_oauth_settings(
        base_url="http://example.com",
        redirect_uris=["http://client.local/callback"],
        resources=[OAuthResource(prefix="/mcp/", scopes=["user"])],
    )

    resolved_resource, error = _resolve_token_resource(
        settings,
        "http://example.com",
        requested_resource="http://example.com/mcp",
        bound_resource="http://example.com/mcp/",
        require_bound_match=True,
    )

    assert error is None
    assert resolved_resource == "http://example.com/mcp/"
