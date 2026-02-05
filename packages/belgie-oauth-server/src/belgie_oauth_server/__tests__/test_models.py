import pytest
from belgie_oauth_server.models import InvalidRedirectUriError, InvalidScopeError, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

BEARER = "Bearer"


def test_oauth_token_normalizes_bearer() -> None:
    token = OAuthToken(access_token="abc", token_type="bearer")
    assert token.token_type == BEARER

    token = OAuthToken(access_token="abc", token_type="BEARER")
    assert token.token_type == BEARER


def test_client_metadata_validate_scope_ok() -> None:
    metadata = OAuthClientMetadata(redirect_uris=["http://example.com/callback"], scope="user admin")
    assert metadata.validate_scope("user") == ["user"]


def test_client_metadata_validate_scope_missing_ok() -> None:
    metadata = OAuthClientMetadata(redirect_uris=["http://example.com/callback"], scope="user")
    assert metadata.validate_scope(None) is None


def test_client_metadata_validate_scope_invalid() -> None:
    metadata = OAuthClientMetadata(redirect_uris=["http://example.com/callback"], scope="user")

    with pytest.raises(InvalidScopeError):
        metadata.validate_scope("admin")


def test_client_metadata_validate_redirect_uri_with_single_default() -> None:
    metadata = OAuthClientMetadata(redirect_uris=["http://example.com/callback"])
    assert str(metadata.validate_redirect_uri(None)) == "http://example.com/callback"


def test_client_metadata_validate_redirect_uri_explicit_ok() -> None:
    metadata = OAuthClientMetadata(redirect_uris=["http://example.com/callback"])
    assert str(metadata.validate_redirect_uri(AnyUrl("http://example.com/callback"))) == "http://example.com/callback"


def test_client_metadata_validate_redirect_uri_invalid() -> None:
    metadata = OAuthClientMetadata(redirect_uris=["http://example.com/callback"])

    with pytest.raises(InvalidRedirectUriError):
        metadata.validate_redirect_uri(AnyUrl("http://example.com/other"))
