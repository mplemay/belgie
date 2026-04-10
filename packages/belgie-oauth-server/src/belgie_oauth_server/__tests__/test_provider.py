from urllib.parse import parse_qs, urlparse

import pytest
from belgie_oauth_server import provider as provider_module
from belgie_oauth_server.models import OAuthClientMetadata
from belgie_oauth_server.provider import AccessToken, AuthorizationParams, RefreshToken, SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import create_code_challenge


@pytest.mark.asyncio
async def test_provider_authorize_and_issue_code() -> None:
    settings = OAuthServer(
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
async def test_provider_issue_authorization_code_includes_issuer() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-iss",
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=settings.redirect_uris[0],
            redirect_uri_provided_explicitly=True,
        ),
    )

    redirect_url = await provider.issue_authorization_code("state-iss", issuer=str(settings.issuer_url))
    query = parse_qs(urlparse(redirect_url).query)

    assert query["iss"] == [str(settings.issuer_url)]


@pytest.mark.asyncio
async def test_provider_authorize_state_carries_nonce_user_and_session() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-principal",
        scopes=["openid", "profile"],
        code_challenge="challenge",
        redirect_uri=settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource="http://example.com/mcp",
        nonce="nonce-123",
        prompt="create",
        intent="create",
        individual_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    await provider.authorize(oauth_client, params)
    state_data = await provider.load_authorization_state("state-principal")
    assert state_data is not None
    assert state_data.prompt == "create"
    assert state_data.intent == "create"

    redirect_url = await provider.issue_authorization_code("state-principal")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)

    assert authorization_code is not None
    assert authorization_code.nonce == "nonce-123"
    assert authorization_code.individual_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert authorization_code.session_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert authorization_code.resource == "http://example.com/mcp"


@pytest.mark.asyncio
async def test_exchange_authorization_code_issues_token() -> None:
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
async def test_issue_refresh_token_uses_refresh_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
        access_token_ttl_seconds=300,
        refresh_token_ttl_seconds=7200,
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    monkeypatch.setattr(provider_module.time, "time", lambda: 1000.0)

    refresh = provider._issue_refresh_token(client_id="test-client", scopes=["user"])

    assert refresh.expires_at == 8200


@pytest.mark.asyncio
async def test_exchange_refresh_token_preserves_resource_binding() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    refresh = provider._issue_refresh_token(
        client_id="test-client",
        scopes=["openid", "offline_access"],
        resource="http://example.com/mcp",
        individual_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )

    token = await provider.exchange_refresh_token(
        refresh,
        ["openid", "offline_access"],
        access_token_resource=["http://example.com/mcp", "http://example.com/userinfo"],
        refresh_token_resource="http://example.com/mcp",
    )

    assert token.refresh_token is not None
    rotated_refresh = provider.refresh_tokens[token.refresh_token]
    assert rotated_refresh.resource == "http://example.com/mcp"
    assert rotated_refresh.individual_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert rotated_refresh.session_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_exchange_refresh_token_rejects_scope_escalation() -> None:
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
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
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    client = provider.clients["test-client"]

    with pytest.raises(ValueError, match="Client was not registered with scope admin"):
        provider.validate_scopes_for_client(client, ["admin"])


@pytest.mark.asyncio
async def test_consent_storage_supports_subset_checks() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    await provider.save_consent("test-client", "user-123", ["user", "openid"])

    consent = await provider.load_consent("test-client", "user-123")

    assert consent is not None
    assert consent.scopes == ["user", "openid"]
    assert await provider.has_consent("test-client", "user-123", ["user"]) is True
    assert await provider.has_consent("test-client", "user-123", ["user", "openid"]) is True
    assert await provider.has_consent("test-client", "user-123", ["user", "email"]) is False


@pytest.mark.asyncio
async def test_scope_less_dynamic_clients_fall_back_to_default_scope() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    client = await provider.register_client(
        OAuthClientMetadata(
            redirect_uris=["http://example.com/callback"],
            token_endpoint_auth_method="none",
        ),
    )

    assert client.scope is None
    assert provider.default_scopes_for_client(client) == ["user"]
    provider.validate_scopes_for_client(client, ["user"])

    with pytest.raises(ValueError, match="Client was not registered with scope admin"):
        provider.validate_scopes_for_client(client, ["admin"])


def test_validate_client_metadata_rejects_unsupported_grant_type() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    with pytest.raises(ValueError, match="unsupported grant_type implicit"):
        provider.validate_client_metadata(
            OAuthClientMetadata(
                redirect_uris=["http://example.com/callback"],
                grant_types=["implicit"],
            ),
        )


def test_validate_client_metadata_rejects_unsupported_response_type() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    with pytest.raises(ValueError, match="unsupported response_type token"):
        provider.validate_client_metadata(
            OAuthClientMetadata(
                redirect_uris=["http://example.com/callback"],
                response_types=["token"],
            ),
        )


@pytest.mark.parametrize(
    ("token_endpoint_auth_method", "client_type", "message"),
    [
        ("none", "web", "Type must be native or user-agent-based for public clients"),
        ("client_secret_post", "native", "Type must be web for confidential clients"),
    ],
)
def test_validate_client_metadata_rejects_invalid_type_for_auth_method(
    token_endpoint_auth_method: str,
    client_type: str,
    message: str,
) -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    with pytest.raises(ValueError, match=message):
        provider.validate_client_metadata(
            OAuthClientMetadata(
                redirect_uris=["http://example.com/callback"],
                token_endpoint_auth_method=token_endpoint_auth_method,
                type=client_type,
            ),
        )


def test_validate_client_metadata_rejects_pairwise_without_secret() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    with pytest.raises(ValueError, match="pairwise subject_type requires pairwise_secret configuration"):
        provider.validate_client_metadata(
            OAuthClientMetadata(
                redirect_uris=["http://example.com/callback"],
                subject_type="pairwise",
            ),
        )


def test_validate_client_metadata_rejects_require_pkce_false() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))

    with pytest.raises(ValueError, match="pkce is required for registered clients"):
        provider.validate_client_metadata(
            OAuthClientMetadata(
                redirect_uris=["http://example.com/callback"],
                require_pkce=False,
            ),
        )


def test_resolve_subject_identifier_uses_pairwise_secret() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
        pairwise_secret="pairwise-secret",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    pairwise_client = provider.clients["test-client"].model_copy(
        update={
            "subject_type": "pairwise",
            "redirect_uris": ["http://example.com/callback"],
        },
    )

    first_subject = provider.resolve_subject_identifier(
        pairwise_client,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    second_subject = provider.resolve_subject_identifier(
        pairwise_client,
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )

    assert first_subject == second_subject
    assert first_subject != "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
