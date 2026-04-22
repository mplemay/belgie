from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.testing import InMemoryConsent, InMemoryDBConnection, InMemoryOAuthServerAdapter
from belgie_oauth_server.utils import create_code_challenge
from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey
from pydantic import SecretStr

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServer

ACCESS_TOKEN_HINT = "access_token"  # noqa: S105
BEARER_TOKEN_TYPE = "Bearer"  # noqa: S105
REFRESH_TOKEN_HINT = "refresh_token"  # noqa: S105
TEST_CLIENT_ID = "test-client"
TEST_DEFAULT_REDIRECT = "https://client.local/callback"
TEST_CLIENT_SECRET = "test-secret"  # noqa: S105


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeUser:
    id: UUID = field(default_factory=uuid4)
    email: str = "person@example.com"
    name: str | None = "Test User"
    image: str | None = "https://example.com/avatar.png"
    email_verified_at: datetime | None = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeSession:
    id: UUID = field(default_factory=uuid4)
    created_at: datetime | None = field(default_factory=lambda: datetime.now(UTC))


class FakeSessionManager:
    def __init__(self, client: FakeBelgieClient) -> None:
        self._client = client

    async def get_session(self, _db: object, session_id: UUID) -> FakeSession | None:
        if self._client.signed_out_session_id == session_id:
            return None
        if session_id == self._client.session.id:
            return self._client.session
        return None


class FakeAdapter:
    def __init__(self, user: FakeUser) -> None:
        self.user = user

    async def get_individual_by_id(self, _db: object, individual_id: UUID) -> FakeUser | None:
        if individual_id == self.user.id:
            return self.user
        return None


class FakeBelgieClient:
    def __init__(self, user: FakeUser | None = None, session: FakeSession | None = None) -> None:
        self.user = user or FakeUser()
        self.session = session or FakeSession()
        self.db = InMemoryDBConnection()
        self.adapter = FakeAdapter(self.user)
        self.signed_out_session_id: UUID | None = None
        self.session_manager = FakeSessionManager(self)

    async def get_individual(self, _security_scopes, request):
        if request.headers.get("x-authenticated") != "true":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return self.user

    async def get_session(self, request):
        if request.headers.get("x-authenticated") != "true":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if self.signed_out_session_id == self.session.id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return self.session

    async def sign_out(self, session_id: UUID) -> None:
        self.signed_out_session_id = session_id


class DummyBelgie:
    def __init__(self, client: FakeBelgieClient, settings: BelgieSettings) -> None:
        self._client = client
        self.settings = settings
        self.plugins: list[object] = []

    async def __call__(self) -> FakeBelgieClient:
        return self._client

    async def database(self):
        yield self._client.db


def _build_app(settings: OAuthServer) -> tuple[FastAPI, OAuthServerPlugin, FakeBelgieClient]:
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://testserver")
    plugin = OAuthServerPlugin(belgie_settings, settings)
    belgie_client = FakeBelgieClient()
    belgie = DummyBelgie(belgie_client, belgie_settings)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    app.include_router(plugin.public(belgie))
    assert plugin.provider is not None
    return app, plugin, belgie_client


def _build_fixture(settings: OAuthServer) -> tuple[TestClient, OAuthServerPlugin, FakeBelgieClient]:
    app, plugin, belgie_client = _build_app(settings)
    return TestClient(app), plugin, belgie_client


def _build_settings(**overrides: object) -> OAuthServer:
    return build_oauth_settings(default_scopes=["user"], **overrides)


def _auth_headers() -> dict[str, str]:
    return {"x-authenticated": "true"}


def _authorize_params(
    settings: OAuthServer,
    *,
    state: str,
    scope: str = "user",
    verifier: str = "verifier",
    prompt: str | None = None,
    with_pkce: bool = True,
) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": TEST_CLIENT_ID,
        "redirect_uri": TEST_DEFAULT_REDIRECT,
        "scope": scope,
        "state": state,
    }
    if prompt is not None:
        params["prompt"] = prompt
    if with_pkce:
        params["code_challenge"] = create_code_challenge(verifier)
        params["code_challenge_method"] = "S256"
    return params


def _query(location: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(location).query)


def _decode_id_token(plugin: OAuthServerPlugin, token: str, audience: str) -> dict[str, object]:
    assert plugin.provider is not None
    return plugin.provider.signing_state.decode(
        token,
        audience=audience,
        issuer="http://testserver/auth",
    )


def _decode_access_token(plugin: OAuthServerPlugin, token: str) -> dict[str, object]:
    assert plugin.provider is not None
    return plugin.provider.signing_state.decode(
        token,
        issuer="http://testserver/auth",
    )


def _update_seeded_client(plugin: OAuthServerPlugin, client_id: str, **updates: object) -> None:
    assert plugin.provider is not None
    adapter = plugin.provider.adapter
    if not isinstance(adapter, InMemoryOAuthServerAdapter):
        msg = "integration tests require InMemoryOAuthServerAdapter"
        raise TypeError(msg)
    current = adapter.clients[client_id]
    adapter.clients[client_id] = replace(current, **updates)


def _grant_consent(
    plugin: OAuthServerPlugin,
    client_id: str,
    individual_id: UUID | str,
    scopes: list[str],
    *,
    reference_id: str | None = None,
) -> None:
    assert plugin.provider is not None
    adapter = plugin.provider.adapter
    individual_uuid = individual_id if isinstance(individual_id, UUID) else UUID(str(individual_id))
    adapter.consents[(client_id, individual_uuid, reference_id)] = InMemoryConsent(
        client_id=client_id,
        individual_id=individual_uuid,
        reference_id=reference_id,
        scopes=scopes,
    )


def _authorize_to_next_location(
    client: TestClient,
    settings: OAuthServer,
    *,
    state: str,
    scope: str = "user",
    verifier: str = "verifier",
    prompt: str | None = None,
    with_pkce: bool = True,
    extra_params: dict[str, str] | None = None,
) -> str:
    authorize = client.get(
        "/auth/oauth2/authorize",
        params={
            **_authorize_params(
                settings,
                state=state,
                scope=scope,
                verifier=verifier,
                prompt=prompt,
                with_pkce=with_pkce,
            ),
            **(extra_params or {}),
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert authorize.status_code == 302

    location = authorize.headers["location"]
    if location.startswith("http://testserver/auth/oauth2/login?"):
        login_redirect = client.get(location, headers=_auth_headers(), follow_redirects=False)
        assert login_redirect.status_code == 302
        location = login_redirect.headers["location"]
    return location


def _exchange_code(
    client: TestClient,
    settings: OAuthServer,
    *,
    code: str,
    verifier: str = "verifier",
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    resource: str | None = None,
) -> TestClient:
    payload: dict[str, str] = {
        "grant_type": "authorization_code",
        "client_id": client_id or TEST_CLIENT_ID,
        "code": code,
        "redirect_uri": redirect_uri or TEST_DEFAULT_REDIRECT,
    }
    if verifier:
        payload["code_verifier"] = verifier
    if client_secret is not None:
        if client_secret:
            payload["client_secret"] = client_secret
    else:
        payload["client_secret"] = TEST_CLIENT_SECRET
    if resource is not None:
        payload["resource"] = resource
    return client.post("/auth/oauth2/token", data=payload)


def _authorize_and_return_code(
    client: TestClient,
    settings: OAuthServer,
    *,
    state: str,
    scope: str = "user",
    verifier: str = "verifier",
    prompt: str | None = None,
    with_pkce: bool = True,
    extra_params: dict[str, str] | None = None,
) -> str:
    callback = _authorize_to_next_location(
        client,
        settings,
        state=state,
        scope=scope,
        verifier=verifier,
        prompt=prompt,
        with_pkce=with_pkce,
        extra_params=extra_params,
    )
    return _query(callback)["code"][0]


def _introspect_token(
    client: TestClient,
    settings: OAuthServer,
    token: str,
    *,
    token_type_hint: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> TestClient:
    _ = settings
    payload: dict[str, str] = {"token": token}
    if client_id is not None:
        payload["client_id"] = client_id
    else:
        payload["client_id"] = TEST_CLIENT_ID
    if client_secret is not None:
        payload["client_secret"] = client_secret
    else:
        payload["client_secret"] = TEST_CLIENT_SECRET
    if token_type_hint is not None:
        payload["token_type_hint"] = token_type_hint
    return client.post("/auth/oauth2/introspect", data=payload)


def _revoke_token(
    client: TestClient,
    settings: OAuthServer,
    token: str,
    *,
    token_type_hint: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> TestClient:
    _ = settings
    payload: dict[str, str] = {"token": token}
    if client_id is not None:
        payload["client_id"] = client_id
    else:
        payload["client_id"] = TEST_CLIENT_ID
    if client_secret is not None:
        payload["client_secret"] = client_secret
    else:
        payload["client_secret"] = TEST_CLIENT_SECRET
    if token_type_hint is not None:
        payload["token_type_hint"] = token_type_hint
    return client.post("/auth/oauth2/revoke", data=payload)


def _trust_dynamic_callback_client(oauth_client) -> bool:
    redirect_uris = {str(uri) for uri in oauth_client.redirect_uris or []}
    grant_types = set(oauth_client.grant_types)
    return (
        redirect_uris == {"https://trusted.local/callback"}
        and oauth_client.token_endpoint_auth_method == "none"  # noqa: S105
        and "authorization_code" in grant_types
    )


def test_metadata_and_openapi_match_reference_contract() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    built_in_metadata = client.get("/auth/.well-known/oauth-authorization-server")
    external_metadata = client.get("/.well-known/oauth-authorization-server/auth")
    openid_metadata = client.get("/auth/.well-known/openid-configuration")

    assert built_in_metadata.status_code == 200
    assert external_metadata.status_code == 200
    assert openid_metadata.status_code == 200
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404

    metadata = built_in_metadata.json()
    assert external_metadata.json() == metadata
    assert metadata["issuer"] == "http://testserver/auth"
    assert metadata["authorization_endpoint"] == "http://testserver/auth/oauth2/authorize"
    assert metadata["token_endpoint"] == "http://testserver/auth/oauth2/token"  # noqa: S105
    assert metadata["registration_endpoint"] == "http://testserver/auth/oauth2/register"
    assert metadata["introspection_endpoint"] == "http://testserver/auth/oauth2/introspect"
    assert metadata["revocation_endpoint"] == "http://testserver/auth/oauth2/revoke"
    assert metadata["token_endpoint_auth_methods_supported"] == [
        "client_secret_basic",
        "client_secret_post",
    ]

    openid = openid_metadata.json()
    assert openid["userinfo_endpoint"] == "http://testserver/auth/oauth2/userinfo"
    assert openid["end_session_endpoint"] == "http://testserver/auth/oauth2/end-session"
    assert openid["prompt_values_supported"] == [
        "login",
        "consent",
        "create",
        "select_account",
        "none",
    ]

    schema = client.get("/openapi.json").json()
    assert "/auth/oauth2/authorize" in schema["paths"]
    assert "/auth/oauth2/token" in schema["paths"]
    assert "/auth/oauth2/register" in schema["paths"]
    assert "/auth/oauth2/create-client" in schema["paths"]
    assert "/auth/oauth2/get-client" in schema["paths"]
    assert "/auth/oauth2/get-clients" in schema["paths"]
    assert "/auth/oauth2/public-client" in schema["paths"]
    assert "/auth/oauth2/client/rotate-secret" in schema["paths"]
    assert "/auth/oauth2/get-consent" in schema["paths"]
    assert "/auth/oauth2/get-consents" in schema["paths"]
    assert "/auth/oauth2/update-consent" in schema["paths"]
    assert "/auth/oauth2/delete-consent" in schema["paths"]
    assert "/auth/oauth/authorize" not in schema["paths"]
    assert client.get("/auth/oauth/authorize").status_code == 404
    assert client.get("/.well-known/oauth-protected-resource").status_code == 404


def test_authorize_and_consent_interactions_use_oauth2_paths() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        consent_url="/consent-screen",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user", skip_consent=False)

    authorize = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(settings, state="state-consent", scope="openid user"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    consent_url = authorize.headers["location"]
    assert consent_url.startswith("http://testserver/consent-screen?")
    state = _query(consent_url)["state"][0]
    assert "sig=" in consent_url
    assert "exp=" in consent_url

    approved = client.post(
        "/auth/oauth2/consent",
        data={"state": state, "accept": "true", "scope": "openid user"},
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert approved.status_code == 302
    approved_query = _query(approved.headers["location"])
    assert "code" in approved_query
    assert approved_query["state"] == ["state-consent"]
    assert approved_query["iss"] == ["http://testserver/auth"]

    prompt_none_client, prompt_none_plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        prompt_none_plugin,
        TEST_CLIENT_ID,
        scope="openid user",
        skip_consent=False,
    )

    prompt_none = prompt_none_client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(
            settings,
            state="state-consent-none",
            scope="openid user",
            prompt="none",
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert prompt_none.status_code == 302
    prompt_none_query = _query(prompt_none.headers["location"])
    assert prompt_none_query["error"] == ["consent_required"]
    assert prompt_none_query["iss"] == ["http://testserver/auth"]


def test_request_uri_resolution_uses_stored_params() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        request_uri_resolver=lambda _request_uri, _client_id: {
            "response_type": "code",
            "redirect_uri": "https://client.local/callback",
            "scope": "openid user",
            "state": "state-from-par",
            "code_challenge": create_code_challenge("par-verifier"),
            "code_challenge_method": "S256",
        },
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    response = client.get(
        "/auth/oauth2/authorize",
        params={"client_id": TEST_CLIENT_ID, "request_uri": "urn:belgie:par:test"},
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://client.local/callback?")
    assert "request_uri=" not in response.headers["location"]
    assert _query(response.headers["location"])["state"] == ["state-from-par"]
    assert _query(response.headers["location"])["iss"] == ["http://testserver/auth"]


def test_register_coerces_anonymous_clients_to_public_and_supports_prelogin_lookup() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        allow_public_client_prelogin=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    metadata = client.get("/auth/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    assert metadata.json()["token_endpoint_auth_methods_supported"] == [
        "none",
        "client_secret_basic",
        "client_secret_post",
    ]

    registered = client.post(
        "/auth/oauth2/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user offline_access",
        },
    )

    assert registered.status_code == 201
    payload = registered.json()
    assert payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert payload["grant_types"] == ["authorization_code"]
    assert payload["require_pkce"] is True
    assert "client_secret" not in payload

    public_client = client.get(
        "/auth/oauth2/public-client",
        params={"client_id": payload["client_id"]},
        headers=_auth_headers(),
    )
    assert public_client.status_code == 200
    assert public_client.json()["client_id"] == payload["client_id"]
    assert "redirect_uris" not in public_client.json()

    prelogin = client.post(
        "/auth/oauth2/public-client-prelogin",
        json={"client_id": payload["client_id"]},
    )
    assert prelogin.status_code == 200
    assert prelogin.json() == public_client.json()


def test_authenticated_dynamic_registration_defaults_to_confidential_client() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        allow_dynamic_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth2/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "type": "web",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["token_endpoint_auth_method"] == "client_secret_basic"  # noqa: S105
    assert payload["grant_types"] == ["authorization_code"]
    assert payload["client_secret"]


def test_trusted_dynamic_client_skips_consent_without_persisting_skip_consent() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        trusted_client_resolver=_trust_dynamic_callback_client,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    registration = client.post(
        "/auth/oauth2/register",
        json={
            "redirect_uris": ["https://trusted.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "openid user",
        },
    )

    assert registration.status_code == 201
    registered_client = registration.json()
    assert registered_client["skip_consent"] is False

    authorize = client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "https://trusted.local/callback",
            "scope": "openid user",
            "state": "trusted-dynamic-state",
            "code_challenge": create_code_challenge("trusted-dynamic-verifier"),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    assert authorize.headers["location"].startswith("https://trusted.local/callback?")


def test_admin_create_client_allows_confidential_pkce_opt_out() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
    )
    client, plugin, belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/admin/oauth2/create-client",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
            "require_pkce": False,
        },
        headers=_auth_headers(),
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["token_endpoint_auth_method"] == "client_secret_post"  # noqa: S105
    assert payload["require_pkce"] is False

    _grant_consent(plugin, payload["client_id"], belgie_client.user.id, ["openid", "user"])
    authorize = client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": payload["client_id"],
            "redirect_uri": "https://client.local/callback",
            "scope": "openid user",
            "state": "state-confidential-no-pkce",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert authorize.status_code == 302

    code = _query(authorize.headers["location"])["code"][0]

    token_response = client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": payload["client_id"],
            "client_secret": payload["client_secret"],
            "code": code,
            "redirect_uri": "https://client.local/callback",
        },
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["access_token"]
    assert token_payload["id_token"]
    assert "refresh_token" not in token_payload


def test_token_resource_is_applied_at_token_and_refresh_time() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        valid_audiences=["http://testserver/mcp", "http://other.local/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user offline_access")

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-resource-token",
        scope="openid user offline_access",
        verifier="resource-verifier",
    )
    code = _query(callback)["code"][0]

    first_token = _exchange_code(
        client,
        settings,
        code=code,
        verifier="resource-verifier",
        resource="http://testserver/mcp",
        client_secret="static-secret",
    )
    assert first_token.status_code == 200
    first_payload = first_token.json()
    first_access_token = _decode_access_token(plugin, first_payload["access_token"])
    assert first_access_token["aud"] == [
        "http://testserver/mcp",
        "http://testserver/auth/oauth2/userinfo",
    ]
    assert first_payload["refresh_token"]

    refreshed = client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": TEST_CLIENT_ID,
            "client_secret": "static-secret",
            "refresh_token": first_payload["refresh_token"],
            "resource": "http://other.local/mcp",
        },
    )
    assert refreshed.status_code == 200
    refreshed_access_token = _decode_access_token(plugin, refreshed.json()["access_token"])
    assert refreshed_access_token["aud"] == [
        "http://other.local/mcp",
        "http://testserver/auth/oauth2/userinfo",
    ]


def test_pairwise_subject_is_stable_across_http_endpoints() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        test_require_pkce=False,
        pairwise_secret=SecretStr("pairwise-secret-for-tests-123456"),
        enable_end_session=True,
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="user openid profile email offline_access",
        subject_type="pairwise",
        enable_end_session=True,
    )

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-pairwise",
        scope="openid profile email offline_access",
        extra_params={"resource": "http://testserver/mcp"},
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        resource="http://testserver/mcp",
        client_secret="static-secret",
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    access_jwt = _decode_access_token(plugin, token_payload["access_token"])
    assert access_jwt["sub"] == str(belgie_client.user.id)
    id_token = _decode_id_token(plugin, token_payload["id_token"], TEST_CLIENT_ID)

    userinfo = client.get(
        "/auth/oauth2/userinfo",
        headers={"authorization": f"Bearer {token_payload['access_token']}"},
    )
    assert userinfo.status_code == 200

    introspection = client.post(
        "/auth/oauth2/introspect",
        data={
            "client_id": TEST_CLIENT_ID,
            "client_secret": "static-secret",
            "token": token_payload["access_token"],
        },
    )
    assert introspection.status_code == 200

    refresh = client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": TEST_CLIENT_ID,
            "client_secret": "static-secret",
            "refresh_token": token_payload["refresh_token"],
        },
    )
    assert refresh.status_code == 200
    refresh_payload = refresh.json()
    refreshed_id_token = _decode_id_token(plugin, refresh_payload["id_token"], TEST_CLIENT_ID)

    refresh_introspection = client.post(
        "/auth/oauth2/introspect",
        data={
            "client_id": TEST_CLIENT_ID,
            "client_secret": "static-secret",
            "token": refresh_payload["refresh_token"],
            "token_type_hint": "refresh_token",
        },
    )
    assert refresh_introspection.status_code == 200

    expected_subject = id_token["sub"]
    assert expected_subject == userinfo.json()["sub"]
    assert expected_subject == introspection.json()["sub"]
    assert expected_subject == refreshed_id_token["sub"]
    assert expected_subject == refresh_introspection.json()["sub"]
    assert expected_subject != str(belgie_client.user.id)
    assert introspection.json()["sid"] == str(belgie_client.session.id)
    assert introspection.json()["iss"] == "http://testserver/auth"


def test_disable_jwt_plugin_issues_opaque_access_tokens_and_hs256_id_tokens() -> None:
    client_secret = "static-secret-for-disable-jwt-tests-123456"  # noqa: S105
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret=client_secret,
        disable_jwt_plugin=True,
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid user",
        client_secret=client_secret,
    )

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-disable-jwt",
        scope="openid user",
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        resource="http://testserver/mcp",
        client_secret=client_secret,
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["access_token"].count(".") == 0
    assert client.get("/auth/jwks").status_code == 404

    id_token = jwt.decode(
        token_payload["id_token"],
        key=OctKey.import_key(client_secret),
        algorithms=["HS256"],
    )
    jwt.JWTClaimsRegistry(
        iss={"essential": True, "value": "http://testserver/auth"},
        aud={"essential": True, "value": TEST_CLIENT_ID},
    ).validate(id_token.claims)
    assert id_token.claims["iss"] == "http://testserver/auth"
    assert id_token.claims["aud"] == TEST_CLIENT_ID


def test_disable_jwt_plugin_omits_id_token_for_public_clients() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret=None,
        disable_jwt_plugin=True,
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid user",
        token_endpoint_auth_method="none",
        client_secret=None,
        client_secret_hash=None,
    )

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-disable-jwt-public",
        scope="openid user",
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        resource="http://testserver/mcp",
        client_secret="",
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["access_token"].count(".") == 0
    assert "id_token" not in token_payload
    assert client.get("/auth/jwks").status_code == 404


def test_custom_claim_callbacks_share_opaque_token_payload_shape() -> None:
    client_secret = "static-secret-for-custom-claims-123456"  # noqa: S105
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret=client_secret,
        disable_jwt_plugin=True,
        valid_audiences=["http://testserver/mcp"],
        custom_access_token_claims=lambda payload: {
            "tenant": (payload.get("metadata") or {}).get("tenant"),
            "subject_kind": "user" if payload.get("user") is not None else "machine",
        },
        custom_userinfo_claims=lambda payload: {
            "tenant_from_jwt": payload["jwt"].get("tenant"),
        },
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid user",
        metadata_json={"tenant": "acme"},
        client_secret=client_secret,
    )

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-custom-claims",
        scope="openid user",
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        resource="http://testserver/mcp",
        client_secret=client_secret,
    )
    token_payload = token_response.json()

    introspection = client.post(
        "/auth/oauth2/introspect",
        data={
            "client_id": TEST_CLIENT_ID,
            "client_secret": client_secret,
            "token": token_payload["access_token"],
        },
    )
    assert introspection.status_code == 200
    assert introspection.json()["tenant"] == "acme"
    assert introspection.json()["subject_kind"] == "user"

    userinfo = client.get(
        "/auth/oauth2/userinfo",
        headers={"authorization": f"Bearer {token_payload['access_token']}"},
    )
    assert userinfo.status_code == 200
    assert userinfo.json()["tenant_from_jwt"] == "acme"


def test_custom_callbacks_cannot_override_reserved_token_fields() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        custom_token_response_fields=lambda _payload: {
            "expires_in": 1,
            "tenant_id": "acme",
        },
        custom_id_token_claims=lambda _payload: {
            "iss": "https://invalid.example",
            "nonce": "tampered",
            "tenant": "acme",
        },
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-reserved-claims",
        scope="openid user",
        extra_params={"nonce": "expected-nonce"},
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(client, settings, code=code, client_secret="static-secret")

    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["tenant_id"] == "acme"
    assert token_payload["expires_in"] != 1

    id_token = _decode_id_token(plugin, token_payload["id_token"], TEST_CLIENT_ID)
    assert id_token["iss"] == "http://testserver/auth"
    assert id_token["nonce"] == "expected-nonce"
    assert id_token["tenant"] == "acme"


def test_revoked_signed_access_token_fails_userinfo_and_introspection() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-revoked-jwt",
        scope="openid user",
        verifier="revoked-verifier",
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="revoked-verifier",
        resource="http://testserver/mcp",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["access_token"].count(".") == 2

    revoke = client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": TEST_CLIENT_ID,
            "client_secret": "static-secret",
            "token": token_payload["access_token"],
            "token_type_hint": "access_token",
        },
    )
    assert revoke.status_code == 200
    assert revoke.json() == {}

    userinfo = client.get(
        "/auth/oauth2/userinfo",
        headers={"authorization": f"Bearer {token_payload['access_token']}"},
    )
    assert userinfo.status_code == 401
    assert userinfo.json() == {"error": "invalid_token"}

    introspection = client.post(
        "/auth/oauth2/introspect",
        data={
            "client_id": TEST_CLIENT_ID,
            "client_secret": "static-secret",
            "token": token_payload["access_token"],
        },
    )
    assert introspection.status_code == 200
    assert introspection.json() == {"active": False}


def test_client_management_rpc_routes_match_reference_shape() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        allow_public_client_prelogin=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/oauth2/create-client",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
        },
        headers=_auth_headers(),
    )
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    assert created.headers["pragma"] == "no-cache"
    created_payload = created.json()
    client_id = created_payload["client_id"]
    original_secret = created_payload["client_secret"]

    public_client = client.get(
        "/auth/oauth2/public-client",
        params={"client_id": client_id},
        headers=_auth_headers(),
    )
    assert public_client.status_code == 200
    assert public_client.json()["client_id"] == client_id
    assert "redirect_uris" not in public_client.json()

    fetched = client.get(
        "/auth/oauth2/get-client",
        params={"client_id": client_id},
        headers=_auth_headers(),
    )
    assert fetched.status_code == 200
    assert fetched.json()["redirect_uris"] == ["https://client.local/callback"]
    assert "client_secret" not in fetched.json()

    listed = client.get("/auth/oauth2/get-clients", headers=_auth_headers())
    assert listed.status_code == 200
    assert any(item["client_id"] == client_id for item in listed.json())

    updated = client.post(
        "/auth/oauth2/update-client",
        json={"client_id": client_id, "update": {"client_name": "Updated App"}},
        headers=_auth_headers(),
    )
    assert updated.status_code == 200
    assert updated.json()["client_name"] == "Updated App"

    rotated = client.post(
        "/auth/oauth2/client/rotate-secret",
        json={"client_id": client_id},
        headers=_auth_headers(),
    )
    assert rotated.status_code == 200
    assert rotated.headers["cache-control"] == "no-store"
    assert rotated.headers["pragma"] == "no-cache"
    assert rotated.json()["client_secret"] != original_secret

    deleted = client.post(
        "/auth/oauth2/delete-client",
        json={"client_id": client_id},
        headers=_auth_headers(),
    )
    assert deleted.status_code == 200
    assert deleted.json() == {}

    refetched = client.get(
        "/auth/oauth2/get-client",
        params={"client_id": client_id},
        headers=_auth_headers(),
    )
    assert refetched.status_code == 404
    assert refetched.json()["error"] == "not_found"


def test_public_client_routes_ignore_admin_only_fields() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        pairwise_secret="pairwise-secret-for-tests-123456",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/oauth2/create-client",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
            "skip_consent": True,
            "enable_end_session": True,
            "require_pkce": False,
            "subject_type": "pairwise",
            "client_secret_expires_at": 123,
            "metadata": {"tenant": "acme"},
        },
        headers=_auth_headers(),
    )
    assert created.status_code == 201
    created_payload = created.json()
    client_id = created_payload["client_id"]
    assert created_payload["skip_consent"] is False
    assert "enable_end_session" not in created_payload
    assert created_payload["require_pkce"] is True
    assert "subject_type" not in created_payload
    assert created_payload["client_secret_expires_at"] == 0
    assert "tenant" not in created_payload

    updated = client.post(
        "/auth/oauth2/update-client",
        json={
            "client_id": client_id,
            "update": {
                "skip_consent": True,
                "enable_end_session": True,
                "require_pkce": False,
                "subject_type": "pairwise",
                "client_secret_expires_at": 456,
                "metadata": {"tenant": "globex"},
            },
        },
        headers=_auth_headers(),
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["skip_consent"] is False
    assert "enable_end_session" not in updated_payload
    assert updated_payload["require_pkce"] is True
    assert "subject_type" not in updated_payload
    assert updated_payload["client_secret_expires_at"] == 0
    assert "tenant" not in updated_payload

    fetched = client.get(
        "/auth/oauth2/get-client",
        params={"client_id": client_id},
        headers=_auth_headers(),
    )
    assert fetched.status_code == 200
    fetched_payload = fetched.json()
    assert fetched_payload["skip_consent"] is False
    assert "enable_end_session" not in fetched_payload
    assert fetched_payload["require_pkce"] is True
    assert "subject_type" not in fetched_payload
    assert fetched_payload["client_secret_expires_at"] == 0
    assert "tenant" not in fetched_payload


def test_admin_client_routes_support_restricted_fields() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        pairwise_secret="pairwise-secret-for-tests-123456",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/admin/oauth2/create-client",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
            "skip_consent": True,
            "enable_end_session": True,
            "require_pkce": False,
            "subject_type": "pairwise",
            "client_secret_expires_at": 123,
            "metadata": {"tenant": "acme"},
        },
        headers=_auth_headers(),
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["skip_consent"] is True
    assert created_payload["enable_end_session"] is True
    assert created_payload["require_pkce"] is False
    assert created_payload["subject_type"] == "pairwise"
    assert created_payload["client_secret_expires_at"] == 123
    assert created_payload["tenant"] == "acme"

    updated = client.patch(
        "/auth/admin/oauth2/update-client",
        json={
            "client_id": created_payload["client_id"],
            "update": {
                "skip_consent": False,
                "enable_end_session": False,
                "client_secret_expires_at": 456,
                "metadata": {"tenant": "globex"},
                "require_pkce": True,
                "subject_type": "public",
            },
        },
        headers=_auth_headers(),
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["skip_consent"] is False
    assert updated_payload["enable_end_session"] is False
    assert updated_payload["client_secret_expires_at"] == 456
    assert updated_payload["tenant"] == "globex"
    assert updated_payload["require_pkce"] is False
    assert updated_payload["subject_type"] == "pairwise"


def test_consent_management_rpc_routes_match_reference_shape() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _grant_consent(plugin, TEST_CLIENT_ID, belgie_client.user.id, ["user"])

    assert plugin.provider is not None
    adapter = plugin.provider.adapter
    consent = next(iter(adapter.consents.values()))

    listed = client.get("/auth/oauth2/get-consents", headers=_auth_headers())
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": str(consent.id),
            "clientId": TEST_CLIENT_ID,
            "userId": str(belgie_client.user.id),
            "referenceId": None,
            "scopes": ["user"],
            "createdAt": int(consent.created_at.timestamp()),
        },
    ]

    fetched = client.get(
        "/auth/oauth2/get-consent",
        params={"id": str(consent.id)},
        headers=_auth_headers(),
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == str(consent.id)

    updated = client.post(
        "/auth/oauth2/update-consent",
        json={"id": str(consent.id), "update": {"scopes": ["user", "openid"]}},
        headers=_auth_headers(),
    )
    assert updated.status_code == 200
    assert updated.json()["scopes"] == ["user", "openid"]

    deleted = client.post(
        "/auth/oauth2/delete-consent",
        json={"id": str(consent.id)},
        headers=_auth_headers(),
    )
    assert deleted.status_code == 200
    assert deleted.json() == {}

    relisted = client.get("/auth/oauth2/get-consents", headers=_auth_headers())
    assert relisted.status_code == 200
    assert relisted.json() == []


def test_authorize_rate_limit_ignores_x_forwarded_for() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        rate_limit={"authorize": {"window": 60, "max": 1}},
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    first = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(settings, state="state-rate-limit-1"),
        headers={"x-forwarded-for": "203.0.113.1"},
        follow_redirects=False,
    )
    second = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(settings, state="state-rate-limit-2"),
        headers={"x-forwarded-for": "198.51.100.7"},
        follow_redirects=False,
    )

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.json() == {
        "error": "rate_limited",
        "error_description": "too many requests",
    }
    assert "retry-after" in second.headers


def test_authorize_prompt_none_returns_login_required_for_unauthenticated_user() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    response = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(
            settings,
            state="state-login-required",
            scope="openid user",
            prompt="none",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert _query(response.headers["location"]) == {
        "error": ["login_required"],
        "error_description": ["authentication required"],
        "iss": ["http://testserver/auth"],
        "state": ["state-login-required"],
    }


def test_authorize_prompt_none_returns_account_selection_required_when_select_account_is_needed() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        select_account_url="/switch-account",
        select_account_resolver=lambda *_args: True,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    response = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(
            settings,
            state="state-account-selection-required",
            scope="openid user",
            prompt="none",
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert _query(response.headers["location"]) == {
        "error": ["account_selection_required"],
        "error_description": ["End-User account selection is required"],
        "iss": ["http://testserver/auth"],
        "state": ["state-account-selection-required"],
    }


def test_authorize_prompt_none_returns_interaction_required_when_post_login_is_needed() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        post_login_url="/finish-login",
        post_login_resolver=lambda *_args: True,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    response = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(
            settings,
            state="state-interaction-required",
            scope="openid user",
            prompt="none",
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert _query(response.headers["location"]) == {
        "error": ["interaction_required"],
        "error_description": ["End-User interaction is required"],
        "iss": ["http://testserver/auth"],
        "state": ["state-interaction-required"],
    }


def test_request_uri_resolution_discards_front_channel_params_not_in_stored_request() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        request_uri_resolver=lambda _request_uri, _client_id: {
            "response_type": "code",
            "redirect_uri": "https://client.local/callback",
            "scope": "openid user",
            "state": "state-from-par",
            "code_challenge": create_code_challenge("par-verifier"),
            "code_challenge_method": "S256",
        },
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    response = client.get(
        "/auth/oauth2/authorize",
        params={
            "client_id": TEST_CLIENT_ID,
            "request_uri": "urn:belgie:par:stored",
            "redirect_uri": "https://attacker.local/callback",
            "scope": "openid admin",
            "state": "front-channel-state",
            "code_challenge": create_code_challenge("front-channel-verifier"),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://client.local/callback?")
    query = _query(response.headers["location"])
    assert query["state"] == ["state-from-par"]
    assert query["iss"] == ["http://testserver/auth"]

    token_response = _exchange_code(
        client,
        settings,
        code=query["code"][0],
        verifier="par-verifier",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200


def test_public_client_without_pkce_returns_invalid_request() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret=None,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid user",
        token_endpoint_auth_method="none",
        client_secret=None,
        client_secret_hash=None,
    )

    response = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(
            settings,
            state="state-public-no-pkce",
            scope="openid user",
            with_pkce=False,
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = _query(response.headers["location"])
    assert query["error"] == ["invalid_request"]
    assert query["error_description"] == ["pkce is required for public clients"]


def test_offline_access_requires_pkce_even_for_confidential_opt_out_client() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        static_client_require_pkce=False,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user offline_access")

    response = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(
            settings,
            state="state-offline-no-pkce",
            scope="openid offline_access",
            with_pkce=False,
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = _query(response.headers["location"])
    assert query["error"] == ["invalid_request"]
    assert query["error_description"] == ["pkce is required when requesting offline_access scope"]


@pytest.mark.parametrize(
    ("authorize_with_pkce", "exchange_verifier", "expected_error"),
    [
        (True, "", "code_verifier required because PKCE was used in authorization"),
        (False, "unexpected-verifier", "code_verifier provided but PKCE was not used in authorization"),
        (True, "wrong-verifier", "invalid code_verifier"),
    ],
)
def test_token_endpoint_validates_pkce_verifier_consistency(
    authorize_with_pkce,
    exchange_verifier: str,
    expected_error: str,
) -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        static_client_require_pkce=False,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-pkce-consistency",
        scope="openid user",
        verifier="expected-verifier",
        with_pkce=authorize_with_pkce,
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier=exchange_verifier,
        client_secret="static-secret",
    )

    assert token_response.status_code == 400
    assert token_response.json()["error_description"] == expected_error


def test_token_endpoint_accepts_client_secret_basic() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        static_client_require_pkce=False,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid user",
        token_endpoint_auth_method="client_secret_basic",
    )

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-basic-token",
        scope="openid user",
        verifier="basic-verifier",
    )
    basic_credentials = base64.b64encode(
        f"{TEST_CLIENT_ID}:static-secret".encode(),
    ).decode("ascii")
    token_response = client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://client.local/callback",
            "code_verifier": "basic-verifier",
        },
        headers={"Authorization": f"Basic {basic_credentials}"},
    )

    assert token_response.status_code == 200
    assert token_response.json()["token_type"] == BEARER_TOKEN_TYPE


def test_userinfo_requires_authorization_header() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    response = client.get("/auth/oauth2/userinfo")

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "error_description": "authorization header not found"}


def test_userinfo_requires_openid_scope() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user profile email")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-userinfo-no-openid",
        scope="user",
        verifier="userinfo-no-openid",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="userinfo-no-openid",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200

    userinfo = client.get(
        "/auth/oauth2/userinfo",
        headers={"authorization": f"Bearer {token_response.json()['access_token']}"},
    )

    assert userinfo.status_code == 400
    assert userinfo.json() == {"error": "invalid_scope", "error_description": "Missing required scope"}


@pytest.mark.parametrize(
    ("resource", "token_segments"),
    [
        (None, 0),
        ("http://testserver/mcp", 2),
    ],
)
def test_userinfo_returns_full_claims_for_opaque_and_jwt_access_tokens(
    resource: str | None,
    token_segments: int,
) -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid profile email")

    code = _authorize_and_return_code(
        client,
        settings,
        state=f"state-userinfo-{token_segments}",
        scope="openid profile email",
        verifier="userinfo-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="userinfo-verifier",
        resource=resource,
        client_secret="static-secret",
    )
    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]
    assert access_token.count(".") == token_segments

    userinfo = client.get(
        "/auth/oauth2/userinfo",
        headers={"authorization": f"Bearer {access_token}"},
    )

    assert userinfo.status_code == 200
    assert userinfo.json() == {
        "sub": str(belgie_client.user.id),
        "name": "Test User",
        "picture": "https://example.com/avatar.png",
        "given_name": "Test",
        "family_name": "User",
        "email": "person@example.com",
        "email_verified": True,
    }


@pytest.mark.parametrize(
    ("scope", "expected_subset", "unexpected_keys"),
    [
        ("openid", {}, ["name", "picture", "given_name", "family_name", "email", "email_verified"]),
        (
            "openid profile",
            {
                "name": "Test User",
                "picture": "https://example.com/avatar.png",
                "given_name": "Test",
                "family_name": "User",
            },
            ["email", "email_verified"],
        ),
        (
            "openid email",
            {
                "email": "person@example.com",
                "email_verified": True,
            },
            ["name", "picture", "given_name", "family_name"],
        ),
    ],
)
def test_userinfo_filters_claims_by_scope(
    scope: str,
    expected_subset: dict[str, object],
    unexpected_keys: list[str],
) -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid profile email")

    code = _authorize_and_return_code(
        client,
        settings,
        state=f"state-{scope.replace(' ', '-')}",
        scope=scope,
        verifier="userinfo-scope-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="userinfo-scope-verifier",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200

    userinfo = client.get(
        "/auth/oauth2/userinfo",
        headers={"authorization": f"Bearer {token_response.json()['access_token']}"},
    )

    assert userinfo.status_code == 200
    body = userinfo.json()
    assert body["sub"] == str(belgie_client.user.id)
    for key, value in expected_subset.items():
        assert body[key] == value
    for key in unexpected_keys:
        assert key not in body


def test_introspection_requires_client_auth() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid offline_access")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-introspect-auth",
        scope="openid offline_access",
        verifier="introspect-auth-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="introspect-auth-verifier",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200

    introspection = client.post(
        "/auth/oauth2/introspect",
        data={"token": token_response.json()["access_token"]},
    )

    assert introspection.status_code == 401


@pytest.mark.parametrize(
    ("resource", "token_field", "token_type_hint", "expected_active"),
    [
        (None, ACCESS_TOKEN_HINT, ACCESS_TOKEN_HINT, True),
        ("http://testserver/mcp", ACCESS_TOKEN_HINT, ACCESS_TOKEN_HINT, True),
        (None, REFRESH_TOKEN_HINT, ACCESS_TOKEN_HINT, False),
        (None, REFRESH_TOKEN_HINT, REFRESH_TOKEN_HINT, True),
        (None, ACCESS_TOKEN_HINT, REFRESH_TOKEN_HINT, False),
        (None, ACCESS_TOKEN_HINT, None, True),
        (None, REFRESH_TOKEN_HINT, None, True),
    ],
)
def test_introspection_respects_token_type_hints(
    resource: str | None,
    token_field: str,
    token_type_hint: str | None,
    expected_active,
) -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid profile email offline_access")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-introspect-hints",
        scope="openid profile email offline_access",
        verifier="introspect-hints-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="introspect-hints-verifier",
        resource=resource,
        client_secret="static-secret",
    )
    assert token_response.status_code == 200
    tokens = token_response.json()

    introspection = _introspect_token(
        client,
        settings,
        tokens[token_field],
        token_type_hint=token_type_hint,
        client_secret="static-secret",
    )

    assert introspection.status_code == 200
    body = introspection.json()
    assert body["active"] is expected_active
    if expected_active:
        assert body["client_id"] == TEST_CLIENT_ID
        assert body["scope"] == "openid profile email offline_access"
        assert body["sub"] == str(belgie_client.user.id)
        assert body["iss"] == "http://testserver/auth"
        assert body["sid"] == str(belgie_client.session.id)
    else:
        assert body == {"active": False}


def test_refresh_preserves_auth_time_in_id_token() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid offline_access")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-auth-time",
        scope="openid offline_access",
        verifier="auth-time-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="auth-time-verifier",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200
    initial_tokens = token_response.json()

    refreshed = client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": TEST_CLIENT_ID,
            "client_secret": "static-secret",
            "refresh_token": initial_tokens["refresh_token"],
        },
    )
    assert refreshed.status_code == 200

    expected_auth_time = int(belgie_client.session.created_at.timestamp())
    initial_id_token = _decode_id_token(plugin, initial_tokens["id_token"], TEST_CLIENT_ID)
    refreshed_id_token = _decode_id_token(plugin, refreshed.json()["id_token"], TEST_CLIENT_ID)
    assert initial_id_token["auth_time"] == expected_auth_time
    assert refreshed_id_token["auth_time"] == expected_auth_time


def test_end_session_rejects_clients_without_end_session_access() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid offline_access")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-end-session-disabled",
        scope="openid offline_access",
        verifier="end-session-disabled",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="end-session-disabled",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200

    logout = client.get(
        "/auth/oauth2/end-session",
        params={"id_token_hint": token_response.json()["id_token"]},
    )

    assert logout.status_code == 401
    assert logout.json() == {
        "error": "invalid_client",
        "error_description": "client unable to logout",
    }


def test_end_session_clears_session_and_removes_sid_from_introspection() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        enable_end_session=True,
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid profile email offline_access",
        enable_end_session=True,
    )

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-end-session",
        scope="openid profile email offline_access",
        verifier="end-session-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="end-session-verifier",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200
    tokens = token_response.json()

    id_token = _decode_id_token(plugin, tokens["id_token"], TEST_CLIENT_ID)
    assert id_token["sid"] == str(belgie_client.session.id)

    before_logout = _introspect_token(
        client,
        settings,
        tokens["access_token"],
        token_type_hint="access_token",
        client_secret="static-secret",
    )
    assert before_logout.status_code == 200
    assert before_logout.json()["sid"] == str(belgie_client.session.id)

    logout = client.get(
        "/auth/oauth2/end-session",
        params={"id_token_hint": tokens["id_token"]},
    )

    assert logout.status_code == 200
    assert logout.json() == {}
    assert belgie_client.signed_out_session_id == belgie_client.session.id

    access_introspection = _introspect_token(
        client,
        settings,
        tokens["access_token"],
        token_type_hint="access_token",
        client_secret="static-secret",
    )
    refresh_introspection = _introspect_token(
        client,
        settings,
        tokens["refresh_token"],
        token_type_hint="refresh_token",
        client_secret="static-secret",
    )

    assert access_introspection.status_code == 200
    assert access_introspection.json()["active"] is True
    assert "sid" not in access_introspection.json()
    assert refresh_introspection.status_code == 200
    assert refresh_introspection.json()["active"] is True
    assert "sid" not in refresh_introspection.json()


def test_end_session_redirects_to_registered_post_logout_uri() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        enable_end_session=True,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid profile email offline_access",
        post_logout_redirect_uris=["https://client.local/logout"],
        enable_end_session=True,
    )

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-end-session-redirect",
        scope="openid profile email offline_access",
        verifier="end-session-redirect",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="end-session-redirect",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200

    logout = client.get(
        "/auth/oauth2/end-session",
        params={
            "id_token_hint": token_response.json()["id_token"],
            "post_logout_redirect_uri": "https://client.local/logout",
            "state": "logout-state",
        },
        follow_redirects=False,
    )

    assert logout.status_code == 302
    assert logout.headers["location"] == "https://client.local/logout?state=logout-state"


def test_dynamic_registration_rejects_skip_consent() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        allow_dynamic_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth2/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "skip_consent": True,
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_client_metadata",
        "error_description": "skip_consent cannot be set during dynamic client registration",
    }


def test_dynamic_registration_ignores_enable_end_session_but_preserves_logout_redirects() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        allow_dynamic_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth2/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "post_logout_redirect_uris": ["https://client.local/logout"],
            "enable_end_session": True,
            "type": "web",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["post_logout_redirect_uris"] == ["https://client.local/logout"]
    assert "enable_end_session" not in payload


def test_revoke_requires_client_auth() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid offline_access")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-revoke-auth",
        scope="openid offline_access",
        verifier="revoke-auth-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="revoke-auth-verifier",
        client_secret="static-secret",
    )
    assert token_response.status_code == 200

    revoke = client.post(
        "/auth/oauth2/revoke",
        data={"token": token_response.json()["access_token"]},
    )

    assert revoke.status_code == 401


@pytest.mark.parametrize(
    ("resource", "token_field", "token_type_hint", "expected_status", "expected_active"),
    [
        ("http://testserver/mcp", ACCESS_TOKEN_HINT, ACCESS_TOKEN_HINT, 200, False),
        (None, ACCESS_TOKEN_HINT, ACCESS_TOKEN_HINT, 200, False),
        (None, REFRESH_TOKEN_HINT, ACCESS_TOKEN_HINT, 400, True),
        (None, REFRESH_TOKEN_HINT, REFRESH_TOKEN_HINT, 200, False),
        (None, ACCESS_TOKEN_HINT, REFRESH_TOKEN_HINT, 400, True),
        (None, ACCESS_TOKEN_HINT, None, 200, False),
        (None, REFRESH_TOKEN_HINT, None, 200, False),
    ],
)
def test_revoke_respects_token_type_hints(
    resource: str | None,
    token_field: str,
    token_type_hint: str | None,
    expected_status: int,
    expected_active,
) -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        test_client_secret="static-secret",
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid offline_access")

    code = _authorize_and_return_code(
        client,
        settings,
        state="state-revoke-hints",
        scope="openid offline_access",
        verifier="revoke-hints-verifier",
    )
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="revoke-hints-verifier",
        resource=resource,
        client_secret="static-secret",
    )
    assert token_response.status_code == 200
    tokens = token_response.json()

    revoke = _revoke_token(
        client,
        settings,
        tokens[token_field],
        token_type_hint=token_type_hint,
        client_secret="static-secret",
    )

    assert revoke.status_code == expected_status
    if expected_status == 200:
        assert revoke.json() == {}

    introspection = _introspect_token(
        client,
        settings,
        tokens[token_field],
        token_type_hint=REFRESH_TOKEN_HINT if token_field == REFRESH_TOKEN_HINT else ACCESS_TOKEN_HINT,
        client_secret="static-secret",
    )

    assert introspection.status_code == 200
    if expected_active:
        assert introspection.json()["active"] is True
    else:
        assert introspection.json() == {"active": False}


def test_loopback_redirect_uri_allows_port_mismatch_for_public_clients() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["http://127.0.0.1/callback"],
        test_client_secret=None,
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(
        plugin,
        TEST_CLIENT_ID,
        scope="openid user",
        token_endpoint_auth_method="none",
        client_secret=None,
        client_secret_hash=None,
    )
    redirect_uri = "http://127.0.0.1:43123/callback"

    authorize = client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": TEST_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid user",
            "state": "state-loopback-port",
            "code_challenge": create_code_challenge("loopback-port-verifier"),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    assert authorize.headers["location"].startswith(f"{redirect_uri}?")
    code = _query(authorize.headers["location"])["code"][0]
    token_response = _exchange_code(
        client,
        settings,
        code=code,
        verifier="loopback-port-verifier",
        redirect_uri=redirect_uri,
        client_secret="",
    )
    assert token_response.status_code == 200


def test_non_loopback_redirect_uri_rejects_port_mismatch() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    authorize = client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": TEST_CLIENT_ID,
            "redirect_uri": "https://client.local:43123/callback",
            "scope": "openid user",
            "state": "state-non-loopback-port",
            "code_challenge": create_code_challenge("non-loopback-verifier"),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 400
    assert authorize.json() == {
        "error": "invalid_request",
        "error_description": "Redirect URI 'https://client.local:43123/callback' not registered for client",
    }


def test_loopback_redirect_uri_rejects_path_mismatch() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["http://127.0.0.1/callback"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user")

    authorize = client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": TEST_CLIENT_ID,
            "redirect_uri": "http://127.0.0.1:43123/other",
            "scope": "openid user",
            "state": "state-loopback-path",
            "code_challenge": create_code_challenge("loopback-path-verifier"),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 400
    assert authorize.json() == {
        "error": "invalid_request",
        "error_description": "Redirect URI 'http://127.0.0.1:43123/other' not registered for client",
    }


def test_consent_post_with_accept_json_returns_redirect_uri() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
        consent_url="/consent-screen",
    )
    client, plugin, _bc = _build_fixture(settings)
    _update_seeded_client(plugin, TEST_CLIENT_ID, scope="openid user", skip_consent=False)
    authorize = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(settings, state="state-json-consent", scope="openid user"),
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert authorize.status_code == 302
    state = _query(authorize.headers["location"])["state"][0]
    res = client.post(
        "/auth/oauth2/consent",
        json={"state": state, "accept": True, "scope": "openid user"},
        headers={**_auth_headers(), "Accept": "application/json"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "redirect_uri" in data
    assert "code=" in data["redirect_uri"]
    assert "iss=" in data["redirect_uri"]


def test_admin_update_client_accepts_post() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        test_redirect_uris=["https://client.local/callback"],
    )
    client, _plugin, _bc = _build_fixture(settings)
    created = client.post(
        "/auth/admin/oauth2/create-client",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
        },
        headers=_auth_headers(),
    )
    assert created.status_code == 201
    cid = created.json()["client_id"]
    updated = client.post(
        "/auth/admin/oauth2/update-client",
        json={"client_id": cid, "update": {"client_name": "PostMethod"}},
        headers=_auth_headers(),
    )
    assert updated.status_code == 200
    assert updated.json()["client_name"] == "PostMethod"
