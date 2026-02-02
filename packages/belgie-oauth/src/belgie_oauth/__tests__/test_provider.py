from urllib.parse import parse_qs, urlparse

import pytest
from belgie_oauth import provider as provider_module
from belgie_oauth.models import OAuthClientMetadata
from belgie_oauth.provider import AccessToken, AuthorizationParams, SimpleOAuthProvider
from belgie_oauth.settings import OAuthSettings
from belgie_oauth.utils import create_code_challenge


@pytest.mark.asyncio
async def test_provider_authorize_and_issue_code() -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-123",
        scopes=["user"],
        code_challenge="challenge",
        redirect_uri=settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    login_url = await provider.authorize(oauth_client, params)
    assert "/login" in login_url
    assert "state=state-123" in login_url

    redirect_url = await provider.issue_authorization_code("state-123")
    parsed = urlparse(redirect_url)
    query = parse_qs(parsed.query)
    assert "code" in query
    assert query["state"][0] == "state-123"


@pytest.mark.asyncio
async def test_exchange_authorization_code_issues_token() -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    oauth_client = await provider.get_client("test-client")
    verifier = "verifier"
    params = AuthorizationParams(
        state="state-456",
        scopes=["user"],
        code_challenge=create_code_challenge(verifier),
        redirect_uri=settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    await provider.authorize(oauth_client, params)
    redirect_url = await provider.issue_authorization_code("state-456")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    token = await provider.exchange_authorization_code(authorization_code)

    assert token.access_token.startswith("belgie_")


@pytest.mark.asyncio
async def test_load_access_token_purges_expired() -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    provider.tokens["expired"] = AccessToken(
        token="expired",
        client_id="test-client",
        scopes=["user"],
        created_at=0,
        expires_at=0,
        resource=None,
    )
    token = await provider.load_access_token("expired")
    assert token is None
    assert "expired" not in provider.tokens


@pytest.mark.asyncio
async def test_load_access_token_purges_expired_twice() -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    provider.tokens["expired"] = AccessToken(
        token="expired",
        client_id="test-client",
        scopes=["user"],
        created_at=0,
        expires_at=0,
        resource=None,
    )

    token = await provider.load_access_token("expired")
    assert token is None
    token = await provider.load_access_token("expired")
    assert token is None
    assert "expired" not in provider.tokens


@pytest.mark.asyncio
async def test_authorize_rejects_duplicate_state() -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-dup",
        scopes=["user"],
        code_challenge="challenge",
        redirect_uri=settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    await provider.authorize(oauth_client, params)
    with pytest.raises(ValueError, match="Authorization state already exists"):
        await provider.authorize(oauth_client, params)


@pytest.mark.asyncio
async def test_state_mapping_expires_and_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
        state_ttl_seconds=1,
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-expired",
        scopes=["user"],
        code_challenge="challenge",
        redirect_uri=settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    monkeypatch.setattr(provider_module.time, "time", lambda: 1000.0)
    await provider.authorize(oauth_client, params)

    monkeypatch.setattr(provider_module.time, "time", lambda: 1002.0)
    with pytest.raises(ValueError, match="Invalid state parameter"):
        await provider.issue_authorization_code("state-expired")
    assert "state-expired" not in provider.state_mapping


@pytest.mark.asyncio
async def test_register_client_issues_secret_by_default() -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    metadata = OAuthClientMetadata(redirect_uris=["http://example.com/callback"])
    client_info = await provider.register_client(metadata)

    assert client_info.client_id is not None
    assert client_info.client_secret is not None
    assert client_info.client_id_issued_at is not None


@pytest.mark.asyncio
async def test_register_client_no_secret_when_auth_method_none() -> None:
    settings = OAuthSettings(
        redirect_uris=["http://example.com/callback"],
        issuer_url="http://example.com/auth/oauth",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    metadata = OAuthClientMetadata(
        redirect_uris=["http://example.com/callback"],
        token_endpoint_auth_method="none",
    )
    client_info = await provider.register_client(metadata)

    assert client_info.client_secret is None
