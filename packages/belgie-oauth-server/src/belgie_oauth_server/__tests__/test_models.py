import pytest
from pydantic import AnyUrl
from pydantic_core import ValidationError

from belgie_oauth_server.models import (
    InvalidRedirectUriError,
    InvalidScopeError,
    OAuthServerClientMetadata,
    OAuthServerToken,
)

BEARER = "Bearer"


def test_oauth_token_normalizes_bearer() -> None:
    token = OAuthServerToken(access_token="abc", token_type="bearer")
    assert token.token_type == BEARER

    token = OAuthServerToken(access_token="abc", token_type="BEARER")
    assert token.token_type == BEARER


def test_client_metadata_validate_scope_ok() -> None:
    metadata = OAuthServerClientMetadata(redirect_uris=["https://example.com/callback"], scope="user admin")
    assert metadata.validate_scope("user") == ["user"]


def test_client_metadata_validate_scope_missing_ok() -> None:
    metadata = OAuthServerClientMetadata(redirect_uris=["https://example.com/callback"], scope="user")
    assert metadata.validate_scope(None) is None


def test_client_metadata_allows_missing_redirect_uris() -> None:
    metadata = OAuthServerClientMetadata(grant_types=["client_credentials"], response_types=[])
    assert metadata.redirect_uris is None


def test_client_metadata_rejects_empty_redirect_uris() -> None:
    with pytest.raises(ValidationError):
        OAuthServerClientMetadata(redirect_uris=[])


def test_client_metadata_validate_scope_invalid() -> None:
    metadata = OAuthServerClientMetadata(redirect_uris=["https://example.com/callback"], scope="user")

    with pytest.raises(InvalidScopeError):
        metadata.validate_scope("admin")


def test_client_metadata_validate_redirect_uri_with_single_default() -> None:
    metadata = OAuthServerClientMetadata(redirect_uris=["https://example.com/callback"])
    assert str(metadata.validate_redirect_uri(None)) == "https://example.com/callback"


def test_client_metadata_validate_redirect_uri_explicit_ok() -> None:
    metadata = OAuthServerClientMetadata(redirect_uris=["https://example.com/callback"])
    assert str(metadata.validate_redirect_uri(AnyUrl("https://example.com/callback"))) == "https://example.com/callback"


def test_client_metadata_validate_redirect_uri_rejects_loopback_port_mismatch() -> None:
    metadata = OAuthServerClientMetadata(redirect_uris=["http://localhost/callback"])

    with pytest.raises(InvalidRedirectUriError):
        metadata.validate_redirect_uri(AnyUrl("http://localhost:43123/callback"))


def test_client_metadata_validate_redirect_uri_invalid() -> None:
    metadata = OAuthServerClientMetadata(redirect_uris=["https://example.com/callback"])

    with pytest.raises(InvalidRedirectUriError):
        metadata.validate_redirect_uri(AnyUrl("http://example.com/other"))
