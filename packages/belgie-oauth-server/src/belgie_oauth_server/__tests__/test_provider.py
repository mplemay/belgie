from urllib.parse import parse_qs, urlparse

import pytest
from belgie_oauth_server import provider as provider_module
from belgie_oauth_server.models import OAuthClientMetadata
from belgie_oauth_server.provider import AccessToken, AuthorizationParams, RefreshToken, SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServerSettings
from belgie_oauth_server.utils import create_code_challenge


@pytest.mark.asyncio
async def test_provider_authorize_and_issue_code() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
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
    state_value = await provider.authorize(oauth_client, params)
    assert state_value == "state-123"

    redirect_url = await provider.issue_authorization_code("state-123")
    parsed = urlparse(redirect_url)
    query = parse_qs(parsed.query)
    assert "code" in query
    assert query["state"][0] == "state-123"


@pytest.mark.asyncio
async def test_exchange_authorization_code_issues_token() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
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
async def test_exchange_authorization_code_with_offline_access_issues_refresh_token() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    oauth_client = await provider.get_client("test-client")
    verifier = "verifier"
    params = AuthorizationParams(
        state="state-refresh",
        scopes=["user", "offline_access"],
        code_challenge=create_code_challenge(verifier),
        redirect_uri=settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    await provider.authorize(oauth_client, params)
    redirect_url = await provider.issue_authorization_code("state-refresh")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)

    token = await provider.exchange_authorization_code(authorization_code, issue_refresh_token=True)

    assert token.refresh_token is not None
    stored_refresh = await provider.load_refresh_token(token.refresh_token)
    assert stored_refresh is not None
    assert stored_refresh.scopes == ["user", "offline_access"]


@pytest.mark.asyncio
async def test_load_access_token_purges_expired() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
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
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
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
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
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
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
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
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
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
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    metadata = OAuthClientMetadata(
        redirect_uris=["http://example.com/callback"],
        token_endpoint_auth_method="none",
    )
    client_info = await provider.register_client(metadata)

    assert client_info.client_secret is None


@pytest.mark.asyncio
async def test_register_client_rejects_unsupported_auth_method() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    metadata = OAuthClientMetadata(
        redirect_uris=["http://example.com/callback"],
        token_endpoint_auth_method="private_key_jwt",
    )

    with pytest.raises(ValueError, match="unsupported token_endpoint_auth_method"):
        await provider.register_client(metadata)


@pytest.mark.asyncio
async def test_register_client_accepts_client_secret_basic() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    metadata = OAuthClientMetadata(
        redirect_uris=["http://example.com/callback"],
        token_endpoint_auth_method="client_secret_basic",
    )
    client_info = await provider.register_client(metadata)

    assert client_info.client_secret is not None
    assert client_info.token_endpoint_auth_method == "client_secret_basic"  # noqa: S105


@pytest.mark.asyncio
async def test_load_refresh_token_purges_expired() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    provider.refresh_tokens["expired"] = RefreshToken(
        token="expired",
        client_id="test-client",
        scopes=["user"],
        created_at=0,
        expires_at=0,
    )

    token = await provider.load_refresh_token("expired")
    assert token is None
    assert "expired" not in provider.refresh_tokens


@pytest.mark.asyncio
async def test_exchange_refresh_token_rotates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    monkeypatch.setattr(provider_module.time, "time", lambda: 1000.0)
    original_refresh = provider._issue_refresh_token(client_id="test-client", scopes=["user", "offline_access"])

    token = await provider.exchange_refresh_token(original_refresh, ["user"])

    assert token.access_token.startswith("belgie_")
    assert token.refresh_token is not None
    assert original_refresh.token not in provider.refresh_tokens
    assert token.refresh_token in provider.refresh_tokens


@pytest.mark.asyncio
async def test_exchange_refresh_token_rejects_scope_escalation() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    refresh = provider._issue_refresh_token(client_id="test-client", scopes=["user"])

    with pytest.raises(ValueError, match="not granted"):
        await provider.exchange_refresh_token(refresh, ["user", "admin"])


@pytest.mark.asyncio
async def test_issue_client_credentials_token() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    token = await provider.issue_client_credentials_token("test-client", ["user"])

    assert token.access_token.startswith("belgie_")
    assert token.refresh_token is None
    stored = await provider.load_access_token(token.access_token)
    assert stored is not None
    assert stored.client_id == "test-client"
    assert stored.scopes == ["user"]


@pytest.mark.asyncio
async def test_revoke_refresh_token_removes_linked_access_tokens() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    refresh = provider._issue_refresh_token(client_id="test-client", scopes=["user"])
    provider.tokens["access-linked"] = AccessToken(
        token="access-linked",
        client_id="test-client",
        scopes=["user"],
        created_at=0,
        expires_at=99999,
        resource=None,
        refresh_token=refresh.token,
    )

    await provider.revoke_token(refresh)

    assert refresh.token not in provider.refresh_tokens
    assert "access-linked" not in provider.tokens


def test_validate_scopes_for_client_raises_for_unknown_scope() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    client = provider.clients["test-client"]

    with pytest.raises(ValueError, match="Client was not registered with scope admin"):
        provider.validate_scopes_for_client(client, ["admin"])
