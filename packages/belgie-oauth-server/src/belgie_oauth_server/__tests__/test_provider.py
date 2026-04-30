from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import AnyUrl, SecretStr, ValidationError

from belgie_oauth_server import provider as provider_module
from belgie_oauth_server.__tests__.helpers import build_oauth_provider, build_oauth_settings
from belgie_oauth_server.models import OAuthServerClientMetadata
from belgie_oauth_server.provider import AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.testing import InMemoryDBConnection, InMemoryOAuthServerAdapter
from belgie_oauth_server.utils import create_code_challenge

TEST_REDIRECT = AnyUrl("https://example.com/callback")


@pytest.mark.asyncio
async def test_provider_authorize_and_issue_code() -> None:
    settings, provider, _adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-123",
        scopes=["user"],
        code_challenge="challenge",
        redirect_uri=TEST_REDIRECT,
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
async def test_provider_issue_authorization_code_omits_state_when_not_requested() -> None:
    _settings, provider, adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    state_value = await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state=None,
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    assert adapter.authorization_states[state_value].client_state == ""

    redirect_url = await provider.issue_authorization_code(state_value)
    query = parse_qs(urlparse(redirect_url).query)

    assert "code" in query
    assert "state" not in query


@pytest.mark.asyncio
async def test_provider_issue_authorization_code_restores_legacy_null_client_state() -> None:
    _settings, provider, adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-legacy",
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    adapter.authorization_states["state-legacy"].client_state = None

    redirect_url = await provider.issue_authorization_code("state-legacy")
    query = parse_qs(urlparse(redirect_url).query)

    assert "code" in query
    assert query["state"] == ["state-legacy"]


@pytest.mark.asyncio
async def test_provider_closes_async_generator_database_factory() -> None:
    settings = build_oauth_settings(
        adapter=InMemoryOAuthServerAdapter(),
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    db = InMemoryDBConnection()
    closed = False

    async def database():
        nonlocal closed
        try:
            yield db
        finally:
            closed = True

    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url), database_factory=database)

    async with provider._db_session(None) as session:
        assert session is db
        assert closed is False

    assert closed is True


@pytest.mark.asyncio
async def test_provider_issue_authorization_code_includes_issuer() -> None:
    settings, provider, _adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-iss",
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
        ),
    )

    redirect_url = await provider.issue_authorization_code("state-iss", issuer=str(settings.issuer_url))
    query = parse_qs(urlparse(redirect_url).query)

    assert query["iss"] == [str(settings.issuer_url)]


@pytest.mark.asyncio
async def test_provider_authorize_state_carries_nonce_user_and_session() -> None:
    settings, provider, _adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-principal",
        scopes=["openid", "profile"],
        code_challenge="challenge",
        redirect_uri=TEST_REDIRECT,
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
    settings, provider, _adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    verifier = "verifier"
    params = AuthorizationParams(
        state="state-456",
        scopes=["user"],
        code_challenge=create_code_challenge(verifier),
        redirect_uri=TEST_REDIRECT,
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
    settings, provider, _adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    verifier = "verifier"
    params = AuthorizationParams(
        state="state-refresh",
        scopes=["user", "offline_access"],
        code_challenge=create_code_challenge(verifier),
        redirect_uri=TEST_REDIRECT,
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
async def test_refresh_token_encoder_round_trip_supports_load_exchange_and_revoke() -> None:
    settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        refresh_token_encoder=lambda token, session_id: f"wrapped:{session_id}:{token}",
        refresh_token_decoder=lambda token: (
            None if token.split(":", maxsplit=2)[1] == "None" else token.split(":", maxsplit=2)[1],
            token.split(":", maxsplit=2)[2],
        ),
    )

    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    verifier = "wrapped-verifier"
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-refresh-wrapped",
            scopes=["user", "offline_access"],
            code_challenge=create_code_challenge(verifier),
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    redirect_url = await provider.issue_authorization_code("state-refresh-wrapped")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    assert authorization_code is not None

    issued_token = await provider.exchange_authorization_code(authorization_code, issue_refresh_token=True)

    assert issued_token.refresh_token is not None
    assert issued_token.refresh_token.startswith("wrapped:")
    stored_refresh = await provider.load_refresh_token(issued_token.refresh_token)
    assert stored_refresh is not None

    rotated_token = await provider.exchange_refresh_token(stored_refresh, ["user", "offline_access"])

    assert rotated_token.refresh_token is not None
    assert rotated_token.refresh_token.startswith("wrapped:")
    rotated_refresh = await provider.load_refresh_token(rotated_token.refresh_token)
    assert rotated_refresh is not None

    await provider.revoke_token(rotated_refresh)

    assert await provider.load_refresh_token(rotated_token.refresh_token) is None


@pytest.mark.asyncio
async def test_load_access_token_purges_expired() -> None:
    _settings, provider, adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    await adapter.create_access_token(
        db,
        token_hash=provider._hash_value("expired"),
        client_id="test-client",
        scopes=["user"],
        resource=None,
        refresh_token_id=None,
        individual_id=None,
        session_id=None,
        expires_at=datetime.fromtimestamp(0, UTC),
    )
    token = await provider.load_access_token("expired")
    assert token is None
    assert provider._hash_value("expired") not in adapter.access_tokens


@pytest.mark.asyncio
async def test_load_access_token_purges_expired_twice() -> None:
    _settings, provider, adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    await adapter.create_access_token(
        db,
        token_hash=provider._hash_value("expired"),
        client_id="test-client",
        scopes=["user"],
        resource=None,
        refresh_token_id=None,
        individual_id=None,
        session_id=None,
        expires_at=datetime.fromtimestamp(0, UTC),
    )
    token = await provider.load_access_token("expired")
    assert token is None
    token = await provider.load_access_token("expired")
    assert token is None
    assert provider._hash_value("expired") not in adapter.access_tokens


@pytest.mark.asyncio
async def test_authorize_allows_duplicate_client_state_with_distinct_internal_state() -> None:
    settings, provider, adapter, _db = build_oauth_provider(
        base_url="http://example.com",
        test_redirect_uris=["https://example.com/callback"],
    )

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-dup",
        scopes=["user"],
        code_challenge="challenge",
        redirect_uri=TEST_REDIRECT,
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    first_state = await provider.authorize(oauth_client, params)
    second_state = await provider.authorize(oauth_client, params)

    assert first_state == "state-dup"
    assert second_state != "state-dup"
    assert adapter.authorization_states[second_state].client_state == "state-dup"

    redirect_url = await provider.issue_authorization_code(second_state)
    query = parse_qs(urlparse(redirect_url).query)
    assert query["state"] == ["state-dup"]


@pytest.mark.asyncio
async def test_state_mapping_expires_and_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings, provider, adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        state_ttl_seconds=1,
    )

    oauth_client = await provider.get_client("test-client")
    params = AuthorizationParams(
        state="state-expired",
        scopes=["user"],
        code_challenge="challenge",
        redirect_uri=TEST_REDIRECT,
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    monkeypatch.setattr(provider_module.time, "time", lambda: 1000.0)
    await provider.authorize(oauth_client, params)

    monkeypatch.setattr(provider_module.time, "time", lambda: 1002.0)
    with pytest.raises(ValueError, match="Invalid state parameter"):
        await provider.issue_authorization_code("state-expired")
    assert "state-expired" not in adapter.authorization_states


@pytest.mark.asyncio
async def test_state_mapping_does_not_expire_when_ttl_is_non_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, provider, adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        state_ttl_seconds=0,
    )

    oauth_client = await provider.get_client("test-client")
    monkeypatch.setattr(provider_module.time, "time", lambda: 1000.0)
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-non-expiring",
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
        ),
    )

    monkeypatch.setattr(provider_module.time, "time", lambda: 10_000.0)
    await provider.bind_authorization_state(
        "state-non-expiring",
        individual_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    redirect_url = await provider.issue_authorization_code("state-non-expiring")

    assert "code=" in redirect_url
    assert "state-non-expiring" not in adapter.authorization_states


@pytest.mark.asyncio
async def test_register_client_issues_secret_by_default() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    metadata = OAuthServerClientMetadata(redirect_uris=["https://example.com/callback"])
    client_info = await provider.register_client(metadata)

    assert client_info.client_id is not None
    assert client_info.client_secret is not None
    assert client_info.client_id_issued_at is not None
    assert client_info.token_endpoint_auth_method == "client_secret_basic"  # noqa: S105
    assert client_info.grant_types == ["authorization_code"]


@pytest.mark.asyncio
async def test_register_client_no_secret_when_auth_method_none() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    metadata = OAuthServerClientMetadata(
        redirect_uris=["https://example.com/callback"],
        token_endpoint_auth_method="none",
    )
    client_info = await provider.register_client(metadata)

    assert client_info.client_secret is None


@pytest.mark.asyncio
async def test_update_client_rejects_confidential_auth_without_secret() -> None:
    _settings, provider, _adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    client_info = await provider.register_client(
        OAuthServerClientMetadata(
            redirect_uris=["https://example.com/callback"],
            token_endpoint_auth_method="none",
            type="native",
        ),
        db=db,
    )

    with pytest.raises(ValueError, match="stored client secret"):
        await provider.update_client(
            client_info.client_id,
            updates={"token_endpoint_auth_method": "client_secret_post", "type": "web"},
            db=db,
        )

    reloaded_client = await provider.get_client(client_info.client_id, db=db)

    assert reloaded_client is not None
    assert reloaded_client.token_endpoint_auth_method == "none"  # noqa: S105


@pytest.mark.asyncio
async def test_register_client_rejects_unsupported_auth_method() -> None:
    _settings, _provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    with pytest.raises(ValidationError, match="token_endpoint_auth_method"):
        OAuthServerClientMetadata(
            redirect_uris=["https://example.com/callback"],
            token_endpoint_auth_method="private_key_jwt",
        )


@pytest.mark.asyncio
async def test_register_client_accepts_client_secret_basic() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    metadata = OAuthServerClientMetadata(
        redirect_uris=["https://example.com/callback"],
        token_endpoint_auth_method="client_secret_basic",
    )
    client_info = await provider.register_client(metadata)

    assert client_info.client_secret is not None
    assert client_info.token_endpoint_auth_method == "client_secret_basic"  # noqa: S105


@pytest.mark.asyncio
async def test_register_client_preserves_missing_redirect_uris_for_client_credentials() -> None:
    _settings, provider, _adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    metadata = OAuthServerClientMetadata(
        grant_types=["client_credentials"],
        response_types=[],
    )
    client_info = await provider.register_client(metadata, db=db)
    loaded_client = await provider.get_client(client_info.client_id, db=db)

    assert client_info.redirect_uris is None
    assert loaded_client is not None
    assert loaded_client.redirect_uris is None


@pytest.mark.asyncio
async def test_load_refresh_token_purges_expired() -> None:
    _settings, provider, adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    await adapter.create_refresh_token(
        db,
        token_hash=provider._hash_value("expired"),
        client_id="test-client",
        scopes=["user"],
        resource=None,
        individual_id=None,
        session_id=None,
        expires_at=datetime.fromtimestamp(0, UTC),
    )

    token = await provider.load_refresh_token("expired")
    assert token is None
    assert provider._hash_value("expired") not in adapter.refresh_tokens


@pytest.mark.asyncio
async def test_exchange_refresh_token_rotates_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings, provider, adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    monkeypatch.setattr(provider_module.time, "time", lambda: 1000.0)
    original_refresh = await provider._issue_refresh_token(
        db,
        client_id="test-client",
        scopes=["user", "offline_access"],
    )

    token = await provider.exchange_refresh_token(original_refresh, ["user"])

    assert token.access_token.startswith("belgie_")
    assert token.refresh_token is not None
    stored_original = await provider.load_refresh_token(original_refresh.token, include_revoked=True)
    assert stored_original is not None
    assert stored_original.revoked_at == 1000
    assert provider._hash_value(token.refresh_token) in adapter.refresh_tokens


@pytest.mark.asyncio
async def test_issue_refresh_token_uses_refresh_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings, provider, _adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        access_token_ttl_seconds=300,
        refresh_token_ttl_seconds=7200,
    )
    monkeypatch.setattr(provider_module.time, "time", lambda: 1000.0)

    refresh = await provider._issue_refresh_token(db, client_id="test-client", scopes=["user"])

    assert refresh.expires_at == 8200


@pytest.mark.asyncio
async def test_exchange_refresh_token_preserves_resource_binding() -> None:
    _settings, provider, adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    refresh = await provider._issue_refresh_token(
        db,
        client_id="test-client",
        scopes=["openid", "offline_access"],
        resource="http://example.com/mcp",
        individual_id=provider._parse_uuid("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        session_id=provider._parse_uuid("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )

    token = await provider.exchange_refresh_token(
        refresh,
        ["openid", "offline_access"],
        access_token_resource=["http://example.com/mcp", "http://example.com/userinfo"],
        refresh_token_resource="http://example.com/mcp",
    )

    assert token.refresh_token is not None
    rotated_refresh = adapter.refresh_tokens[provider._hash_value(token.refresh_token)]
    assert rotated_refresh.resource == "http://example.com/mcp"
    assert str(rotated_refresh.individual_id) == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert str(rotated_refresh.session_id) == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_exchange_refresh_token_replay_purges_client_individual_family() -> None:
    _settings, provider, adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    individual_id = provider._parse_uuid("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    session_a = provider._parse_uuid("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    session_b = provider._parse_uuid("cccccccc-cccc-cccc-cccc-cccccccccccc")
    assert individual_id is not None
    assert session_a is not None
    assert session_b is not None

    original_refresh = await provider._issue_refresh_token(
        db,
        client_id="test-client",
        scopes=["user"],
        individual_id=individual_id,
        session_id=session_a,
    )
    other_refresh = await provider._issue_refresh_token(
        db,
        client_id="test-client",
        scopes=["user"],
        individual_id=individual_id,
        session_id=session_b,
    )
    rotated_token = await provider.exchange_refresh_token(original_refresh, ["user"])
    other_refresh_id = adapter.refresh_tokens[provider._hash_value(other_refresh.token)].id
    other_access = await provider._issue_access_token(
        db,
        client_id="test-client",
        scopes=["user"],
        refresh_token_id=other_refresh_id,
        refresh_token=other_refresh.token,
        individual_id=individual_id,
        session_id=session_b,
    )

    with pytest.raises(ValueError, match="revoked"):
        await provider.exchange_refresh_token(original_refresh, ["user"])

    assert rotated_token.refresh_token is not None
    assert await provider.load_refresh_token(rotated_token.refresh_token) is None
    assert await provider.load_access_token(rotated_token.access_token) is None
    assert await provider.load_refresh_token(other_refresh.token) is None
    assert await provider.load_access_token(other_access.token) is None


@pytest.mark.asyncio
async def test_exchange_refresh_token_rejects_scope_escalation() -> None:
    _settings, provider, _adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    refresh = await provider._issue_refresh_token(db, client_id="test-client", scopes=["user"])

    with pytest.raises(ValueError, match="not granted"):
        await provider.exchange_refresh_token(refresh, ["user", "admin"])


@pytest.mark.asyncio
async def test_exchange_refresh_token_allows_removing_offline_access() -> None:
    _settings, provider, _adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    refresh = await provider._issue_refresh_token(
        db,
        client_id="test-client",
        scopes=["openid", "offline_access"],
    )

    token = await provider.exchange_refresh_token(refresh, ["openid"])

    assert token.scope == "openid"
    assert token.refresh_token is not None
    stored_access = await provider.load_access_token(token.access_token)
    rotated_refresh = await provider.load_refresh_token(token.refresh_token)
    assert stored_access is not None
    assert stored_access.scopes == ["openid"]
    assert rotated_refresh is not None
    assert rotated_refresh.scopes == ["openid"]


@pytest.mark.asyncio
async def test_issue_client_credentials_token() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    token = await provider.issue_client_credentials_token("test-client", ["user"])

    assert token.access_token.startswith("belgie_")
    assert token.refresh_token is None
    stored = await provider.load_access_token(token.access_token)
    assert stored is not None
    assert stored.client_id == "test-client"
    assert stored.scopes == ["user"]


@pytest.mark.asyncio
async def test_revoke_refresh_token_marks_revoked_and_removes_linked_access_tokens() -> None:
    _settings, provider, adapter, db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    refresh = await provider._issue_refresh_token(db, client_id="test-client", scopes=["user"])
    await adapter.create_access_token(
        db,
        token_hash=provider._hash_value("access-linked"),
        client_id="test-client",
        scopes=["user"],
        resource=None,
        refresh_token_id=adapter.refresh_tokens[provider._hash_value(refresh.token)].id,
        individual_id=None,
        session_id=None,
        expires_at=datetime.fromtimestamp(99999, UTC),
    )

    await provider.revoke_token(refresh)

    stored_refresh = adapter.refresh_tokens[provider._hash_value(refresh.token)]
    assert stored_refresh.revoked_at is not None
    assert await provider.load_refresh_token(refresh.token) is None
    assert provider._hash_value("access-linked") not in adapter.access_tokens


@pytest.mark.asyncio
async def test_validate_scopes_for_client_raises_for_unknown_scope() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    client = await provider.get_client("test-client")
    assert client is not None

    with pytest.raises(ValueError, match="Client was not registered with scope admin"):
        provider.validate_scopes_for_client(client, ["admin"])


@pytest.mark.asyncio
async def test_consent_storage_supports_subset_checks() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    individual_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    await provider.save_consent("test-client", individual_id, ["user", "openid"])
    await provider.save_consent("test-client", individual_id, ["user"])

    consent = await provider.load_consent("test-client", individual_id)

    assert consent is not None
    assert consent.scopes == ["user", "openid"]
    assert await provider.has_consent("test-client", individual_id, ["user"]) is True
    assert await provider.has_consent("test-client", individual_id, ["user", "openid"]) is True
    assert await provider.has_consent("test-client", individual_id, ["user", "email"]) is False


@pytest.mark.asyncio
async def test_scope_less_dynamic_clients_fall_back_to_default_scopes() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        default_scopes=["user", "profile"],
    )
    client = await provider.register_client(
        OAuthServerClientMetadata(
            redirect_uris=["https://example.com/callback"],
            token_endpoint_auth_method="none",
        ),
    )

    assert client.scope == "user profile"
    assert provider.default_scopes_for_client(client) == ["user", "profile"]
    provider.validate_scopes_for_client(client, ["user", "profile"])

    with pytest.raises(ValueError, match="Client was not registered with scope admin"):
        provider.validate_scopes_for_client(client, ["admin"])


@pytest.mark.asyncio
async def test_default_scopes_propagate_through_seeded_client_and_state_fallback() -> None:
    settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        default_scopes=["user", "profile"],
    )

    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    assert oauth_client.scope == "user profile"
    assert provider.default_scopes_for_client(oauth_client) == ["user", "profile"]
    assert settings.supported_scopes()[:2] == ["user", "profile"]

    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-default-scopes",
            scopes=None,
            code_challenge="challenge",
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )

    redirect_url = await provider.issue_authorization_code("state-default-scopes")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)

    assert authorization_code is not None
    assert authorization_code.scopes == ["user", "profile"]


def test_validate_client_metadata_rejects_unsupported_grant_type() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    with pytest.raises(ValueError, match="unsupported grant_type implicit"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=["https://example.com/callback"],
                grant_types=["implicit"],
            ),
        )


def test_validate_client_metadata_rejects_jwks_fields() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )
    for extra in ({"jwks_uri": "https://client.example/jwks.json"}, {"jwks": {"keys": []}}):
        with pytest.raises(ValueError, match="not yet supported"):
            provider.validate_client_metadata(
                OAuthServerClientMetadata.model_validate(
                    {
                        "redirect_uris": ["https://example.com/callback"],
                        "token_endpoint_auth_method": "none",
                        **extra,
                    },
                ),
            )


def test_validate_client_metadata_rejects_grant_type_disabled_by_server() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        grant_types=["client_credentials"],
        login_url=None,
        consent_url=None,
    )

    with pytest.raises(ValueError, match="unsupported grant_type authorization_code"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=["https://example.com/callback"],
            ),
        )


def test_validate_client_metadata_allows_configured_server_scopes() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        default_scopes=["user", "files:read"],
    )

    provider.validate_client_metadata(
        OAuthServerClientMetadata(
            redirect_uris=["https://example.com/callback"],
            token_endpoint_auth_method="none",
            scope="user files:read",
        ),
    )


def test_validate_client_metadata_rejects_unknown_configured_server_scope() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        default_scopes=["user", "files:read"],
    )

    with pytest.raises(ValueError, match="cannot request scope admin"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=["https://example.com/callback"],
                token_endpoint_auth_method="none",
                scope="user admin",
            ),
        )


def test_validate_client_metadata_rejects_unsupported_response_type() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    with pytest.raises(ValueError, match="unsupported response_type token"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=["https://example.com/callback"],
                response_types=["token"],
            ),
        )


def test_validate_client_metadata_allows_client_credentials_without_redirect_uris() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    provider.validate_client_metadata(
        OAuthServerClientMetadata(
            grant_types=["client_credentials"],
            response_types=[],
        ),
    )


def test_validate_client_metadata_rejects_authorization_code_without_redirect_uris() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    with pytest.raises(ValueError, match="Redirect URIs are required for authorization_code clients"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=None,
                grant_types=["authorization_code"],
                response_types=["code"],
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
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    with pytest.raises(ValueError, match=message):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=["https://example.com/callback"],
                token_endpoint_auth_method=token_endpoint_auth_method,
                type=client_type,
            ),
        )


def test_validate_client_metadata_rejects_pairwise_without_secret() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    with pytest.raises(ValueError, match="pairwise subject_type requires pairwise_secret configuration"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=["https://example.com/callback"],
                subject_type="pairwise",
            ),
        )


def test_validate_client_metadata_rejects_pairwise_redirect_uris_on_different_hosts() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        pairwise_secret="pairwise-secret-for-tests-123456",
    )

    with pytest.raises(ValueError, match="must share the same host"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=[
                    "https://app.local/callback",
                    "https://other.local/callback",
                ],
                subject_type="pairwise",
            ),
        )


def test_validate_client_metadata_rejects_require_pkce_false() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    with pytest.raises(ValueError, match="pkce is required for registered clients"):
        provider.validate_client_metadata(
            OAuthServerClientMetadata(
                redirect_uris=["https://example.com/callback"],
                require_pkce=False,
            ),
        )


def test_validate_client_metadata_allows_confidential_pkce_opt_out_when_enabled() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
    )

    provider.validate_client_metadata(
        OAuthServerClientMetadata(
            redirect_uris=["https://example.com/callback"],
            token_endpoint_auth_method="client_secret_post",
            type="web",
            require_pkce=False,
        ),
        allow_confidential_pkce_opt_out=True,
    )


@pytest.mark.asyncio
async def test_resolve_subject_identifier_uses_pairwise_secret() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        pairwise_secret=SecretStr("pairwise-secret-for-tests-123456"),
    )
    oauth = await provider.get_client("test-client")
    assert oauth is not None
    pairwise_client = oauth.model_copy(
        update={
            "subject_type": "pairwise",
            "redirect_uris": [TEST_REDIRECT],
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
