from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from belgie_core.core.settings import BelgieSettings
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.testing import InMemoryConsent, InMemoryDBConnection
from belgie_oauth_server.utils import create_code_challenge
from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServer


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

    async def get_individual(self, _security_scopes, request):
        if request.headers.get("x-authenticated") != "true":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return self.user

    async def get_session(self, request):
        if request.headers.get("x-authenticated") != "true":
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
    plugin.provider.static_client = plugin.provider.static_client.model_copy(update={"skip_consent": True})
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
        "client_id": settings.client_id,
        "redirect_uri": str(settings.redirect_uris[0]),
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


def _update_static_client(plugin: OAuthServerPlugin, client_id: str, **updates: object) -> None:
    assert plugin.provider is not None
    assert plugin.provider.static_client.client_id == client_id
    plugin.provider.static_client = plugin.provider.static_client.model_copy(update=updates)


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
        "client_id": client_id or settings.client_id,
        "code": code,
        "redirect_uri": redirect_uri or str(settings.redirect_uris[0]),
    }
    if verifier:
        payload["code_verifier"] = verifier
    if client_secret is not None:
        payload["client_secret"] = client_secret
    elif settings.client_secret is not None:
        payload["client_secret"] = settings.client_secret.get_secret_value()
    if resource is not None:
        payload["resource"] = resource
    return client.post("/auth/oauth2/token", data=payload)


def _trust_dynamic_callback_client(oauth_client) -> bool:
    redirect_uris = {str(uri) for uri in oauth_client.redirect_uris or []}
    grant_types = set(oauth_client.grant_types)
    return (
        redirect_uris == {"https://trusted.local/callback"}
        and oauth_client.token_endpoint_auth_method == "none"  # noqa: S105
        and "authorization_code" in grant_types
    )


def test_metadata_and_openapi_match_better_auth_contract() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        consent_url="/consent-screen",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="openid user", skip_consent=False)

    authorize = client.get(
        "/auth/oauth2/authorize",
        params=_authorize_params(settings, state="state-consent", scope="openid user"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    assert authorize.headers["location"].startswith("http://testserver/auth/oauth2/login?")
    state = _query(authorize.headers["location"])["state"][0]

    consent_redirect = client.get(authorize.headers["location"], headers=_auth_headers(), follow_redirects=False)
    assert consent_redirect.status_code == 302
    assert consent_redirect.headers["location"].startswith("http://testserver/consent-screen?")
    assert _query(consent_redirect.headers["location"])["return_to"] == [
        f"http://testserver/auth/oauth2/consent?state={state}",
    ]

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
    _update_static_client(
        prompt_none_plugin,
        settings.client_id,
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        request_uri_resolver=lambda _request_uri, _client_id: {
            "response_type": "code",
            "redirect_uri": "http://client.local/callback",
            "scope": "openid user",
            "state": "state-from-par",
            "code_challenge": create_code_challenge("par-verifier"),
            "code_challenge_method": "S256",
        },
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="openid user")

    response = client.get(
        "/auth/oauth2/authorize",
        params={"client_id": settings.client_id, "request_uri": "urn:belgie:par:test"},
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("http://client.local/callback?")
    assert "request_uri=" not in response.headers["location"]
    assert _query(response.headers["location"])["state"] == ["state-from-par"]
    assert _query(response.headers["location"])["iss"] == ["http://testserver/auth"]


def test_register_coerces_anonymous_clients_to_public_and_supports_prelogin_lookup() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
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


def test_create_client_allows_confidential_pkce_opt_out() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, plugin, belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/oauth2/create-client",
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        valid_audiences=["http://testserver/mcp", "http://other.local/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="openid user offline_access")

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
            "client_id": settings.client_id,
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        static_client_require_pkce=False,
        pairwise_secret="pairwise-secret-for-tests-123456",
        enable_end_session=True,
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_static_client(
        plugin,
        settings.client_id,
        scope="user openid profile email offline_access",
        subject_type="pairwise",
    )

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-pairwise",
        scope="openid profile email offline_access",
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(client, settings, code=code)

    assert token_response.status_code == 200
    token_payload = token_response.json()
    id_token = _decode_id_token(plugin, token_payload["id_token"], settings.client_id)

    userinfo = client.get(
        "/auth/oauth2/userinfo",
        headers={"authorization": f"Bearer {token_payload['access_token']}"},
    )
    assert userinfo.status_code == 200

    introspection = client.post(
        "/auth/oauth2/introspect",
        data={
            "client_id": settings.client_id,
            "client_secret": "static-secret",
            "token": token_payload["access_token"],
        },
    )
    assert introspection.status_code == 200

    refresh = client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.client_id,
            "client_secret": "static-secret",
            "refresh_token": token_payload["refresh_token"],
        },
    )
    assert refresh.status_code == 200
    refresh_payload = refresh.json()
    refreshed_id_token = _decode_id_token(plugin, refresh_payload["id_token"], settings.client_id)

    refresh_introspection = client.post(
        "/auth/oauth2/introspect",
        data={
            "client_id": settings.client_id,
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret=client_secret,
        disable_jwt_plugin=True,
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="openid user")

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
        aud={"essential": True, "value": settings.client_id},
    ).validate(id_token.claims)
    assert id_token.claims["iss"] == "http://testserver/auth"
    assert id_token.claims["aud"] == settings.client_id


def test_disable_jwt_plugin_omits_id_token_for_public_clients() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        disable_jwt_plugin=True,
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="openid user")

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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret=client_secret,
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
    _update_static_client(plugin, settings.client_id, scope="openid user", metadata_json={"tenant": "acme"})

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
    )
    token_payload = token_response.json()

    introspection = client.post(
        "/auth/oauth2/introspect",
        data={
            "client_id": settings.client_id,
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
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
    _update_static_client(plugin, settings.client_id, scope="openid user")

    callback = _authorize_to_next_location(
        client,
        settings,
        state="state-reserved-claims",
        scope="openid user",
        extra_params={"nonce": "expected-nonce"},
    )
    code = _query(callback)["code"][0]
    token_response = _exchange_code(client, settings, code=code)

    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["tenant_id"] == "acme"
    assert token_payload["expires_in"] != 1

    id_token = _decode_id_token(plugin, token_payload["id_token"], settings.client_id)
    assert id_token["iss"] == "http://testserver/auth"
    assert id_token["nonce"] == "expected-nonce"
    assert id_token["tenant"] == "acme"


def test_revoked_signed_access_token_fails_userinfo_and_introspection() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        valid_audiences=["http://testserver/mcp"],
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="openid user")

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
    )
    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["access_token"].count(".") == 2

    revoke = client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": settings.client_id,
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
            "client_id": settings.client_id,
            "client_secret": "static-secret",
            "token": token_payload["access_token"],
        },
    )
    assert introspection.status_code == 200
    assert introspection.json() == {"active": False}


def test_client_management_rpc_routes_match_better_auth_shape() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
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


def test_consent_management_rpc_routes_match_better_auth_shape() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _grant_consent(plugin, settings.client_id, belgie_client.user.id, ["user"])

    assert plugin.provider is not None
    adapter = plugin.provider.adapter
    consent = next(iter(adapter.consents.values()))

    listed = client.get("/auth/oauth2/get-consents", headers=_auth_headers())
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": str(consent.id),
            "clientId": settings.client_id,
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
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
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
