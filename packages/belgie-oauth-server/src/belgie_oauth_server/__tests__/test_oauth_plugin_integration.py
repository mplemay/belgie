from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import jwt
import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.plugin import OAuthServerPlugin, _id_token_signing_key
from belgie_oauth_server.settings import OAuthResource, OAuthServer
from belgie_oauth_server.testing import InMemoryDBConnection
from belgie_oauth_server.utils import create_code_challenge
from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.testclient import TestClient


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


def _build_app(
    settings: OAuthServer,
) -> tuple[FastAPI, OAuthServerPlugin, FakeBelgieClient]:
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://testserver")
    plugin = OAuthServerPlugin(belgie_settings, settings)
    belgie_client = FakeBelgieClient()
    belgie = DummyBelgie(belgie_client, belgie_settings)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    return app, plugin, belgie_client


def _build_fixture(
    settings: OAuthServer,
) -> tuple[TestClient, OAuthServerPlugin, FakeBelgieClient]:
    app, plugin, belgie_client = _build_app(settings)
    return TestClient(app), plugin, belgie_client


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


def _update_static_client(plugin: OAuthServerPlugin, client_id: str, **updates: object) -> None:
    assert plugin.provider is not None
    assert plugin.provider.static_client.client_id == client_id
    plugin.provider.static_client = plugin.provider.static_client.model_copy(update=updates)


def _build_settings(**overrides: object) -> OAuthServer:
    return build_oauth_settings(**overrides)


def test_authorize_success_and_error_redirects_include_iss() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    success = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-success"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert success.status_code == 302
    success_query = _query(success.headers["location"])
    assert "code" in success_query
    assert success_query["state"] == ["state-success"]
    assert success_query["iss"] == ["http://testserver/auth/oauth"]

    error_response = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-error", with_pkce=False),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert error_response.status_code == 302
    error_query = _query(error_response.headers["location"])
    assert error_query["error"] == ["invalid_request"]
    assert error_query["error_description"] == ["pkce is required for public clients"]
    assert error_query["state"] == ["state-error"]
    assert error_query["iss"] == ["http://testserver/auth/oauth"]


def test_prompt_none_returns_login_required_without_redirecting_to_interaction() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-none", prompt="none"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("http://client.local/callback?")
    query = _query(response.headers["location"])
    assert query["error"] == ["login_required"]
    assert query["error_description"] == ["authentication required"]
    assert query["iss"] == ["http://testserver/auth/oauth"]


def test_prompt_none_combination_returns_login_required() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-none-login", prompt="none login"),
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = _query(response.headers["location"])
    assert query["error"] == ["login_required"]
    assert query["error_description"] == ["authentication required"]
    assert query["iss"] == ["http://testserver/auth/oauth"]


def test_authorize_rejects_select_account_prompt_without_select_account_url() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        login_url="/login-screen",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-select-account", prompt="select_account"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = _query(response.headers["location"])
    assert query["error"] == ["invalid_request"]
    assert query["error_description"] == ["unsupported prompt type"]
    assert query["state"] == ["state-select-account"]
    assert query["iss"] == ["http://testserver/auth/oauth"]


def test_authorize_uses_request_uri_resolver() -> None:
    def resolve_request_uri(request_uri: str, client_id: str) -> dict[str, str] | None:
        if request_uri != "urn:belgie:authorize:123":
            return None
        return {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://client.local/callback",
            "scope": "user",
            "state": "resolved-state",
            "code_challenge": create_code_challenge("verifier"),
            "code_challenge_method": "S256",
        }

    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        request_uri_resolver=resolve_request_uri,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get(
        "/auth/oauth/authorize",
        params={"client_id": settings.client_id, "request_uri": "urn:belgie:authorize:123"},
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = _query(response.headers["location"])
    assert "code" in query
    assert query["state"] == ["resolved-state"]
    assert query["iss"] == ["http://testserver/auth/oauth"]


def test_authorize_consent_flow_persists_and_requires_reconsent_for_expanded_scopes() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        login_url="/login-screen",
        consent_url="/consent-screen",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="user openid")

    first_authorize = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-consent-1"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert first_authorize.status_code == 302
    assert first_authorize.headers["location"].startswith("http://testserver/auth/oauth/login?")

    state = _query(first_authorize.headers["location"])["state"][0]
    consent_redirect = client.get(first_authorize.headers["location"], follow_redirects=False)

    assert consent_redirect.status_code == 302
    assert consent_redirect.headers["location"].startswith("http://testserver/consent-screen?")
    assert _query(consent_redirect.headers["location"])["return_to"] == [
        f"http://testserver/auth/oauth/consent?state={state}",
    ]

    approved = client.post(
        "/auth/oauth/consent",
        data={"state": state, "accept": "true", "scope": "user"},
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert approved.status_code == 302
    approved_query = _query(approved.headers["location"])
    assert "code" in approved_query
    assert approved_query["iss"] == ["http://testserver/auth/oauth"]

    repeated = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-consent-2"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert repeated.status_code == 302
    assert repeated.headers["location"].startswith("http://client.local/callback?")

    expanded = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-consent-3", scope="user openid"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert expanded.status_code == 302
    assert expanded.headers["location"].startswith("http://testserver/auth/oauth/login?")


def test_prompt_none_returns_consent_required_when_consent_is_missing() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        consent_url="/consent-screen",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-consent-none", prompt="none"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = _query(response.headers["location"])
    assert query["error"] == ["consent_required"]
    assert query["error_description"] == ["End-User consent is required"]
    assert query["iss"] == ["http://testserver/auth/oauth"]


def test_select_account_flow_resumes_and_prompt_none_returns_account_selection_required() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        select_account_url="/select-account",
        select_account_resolver=lambda *_args: True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    selection_required = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-select-1"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert selection_required.status_code == 302
    assert selection_required.headers["location"].startswith("http://testserver/auth/oauth/login?")

    state = _query(selection_required.headers["location"])["state"][0]
    select_redirect = client.get(selection_required.headers["location"], follow_redirects=False)

    assert select_redirect.status_code == 302
    assert select_redirect.headers["location"].startswith("http://testserver/select-account?")
    assert _query(select_redirect.headers["location"])["return_to"] == [
        f"http://testserver/auth/oauth/continue?state={state}&selected=true",
    ]

    continued = client.get(
        f"/auth/oauth/continue?state={state}&selected=true",
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert continued.status_code == 302
    continued_query = _query(continued.headers["location"])
    assert "code" in continued_query
    assert continued_query["iss"] == ["http://testserver/auth/oauth"]

    prompt_none = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-select-none", prompt="none"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert prompt_none.status_code == 302
    prompt_none_query = _query(prompt_none.headers["location"])
    assert prompt_none_query["error"] == ["account_selection_required"]
    assert prompt_none_query["error_description"] == ["End-User account selection is required"]
    assert prompt_none_query["iss"] == ["http://testserver/auth/oauth"]


def test_openapi_generation_succeeds_with_continue_and_consent_routes() -> None:
    app, _plugin, _belgie_client = _build_app(
        _build_settings(
            base_url="http://testserver",
            redirect_uris=["http://client.local/callback"],
            client_id="test-client",
            login_url="/login-screen",
            consent_url="/consent-screen",
            select_account_url="/select-account",
        ),
    )

    schema = app.openapi()

    assert "/auth/oauth/continue" in schema["paths"]
    assert "/auth/oauth/consent" in schema["paths"]


def test_register_rejects_unauthenticated_confidential_clients_and_allows_public_clients() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    confidential = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["http://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )

    assert confidential.status_code == 401
    assert confidential.json() == {
        "error": "invalid_request",
        "error_description": "authentication required for confidential client registration",
    }

    public = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["http://client.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "user",
        },
    )

    assert public.status_code == 201
    payload = public.json()
    assert payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert "client_secret" not in payload
    assert payload["require_pkce"] is True


def test_register_allows_public_clients_with_configured_resource_scopes() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        resources=[OAuthResource(prefix="/mcp", scopes=["user", "files:read"])],
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["http://client.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "user files:read",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["scope"] == "user files:read"
    assert payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert "client_secret" not in payload


def test_confidential_pkce_requirements_and_token_mismatch_cases() -> None:
    require_pkce_settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
    )
    require_pkce_client, _plugin, _belgie_client = _build_fixture(require_pkce_settings)

    require_pkce_response = require_pkce_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(require_pkce_settings, state="state-confidential-required", with_pkce=False),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert require_pkce_response.status_code == 302
    assert _query(require_pkce_response.headers["location"])["error_description"] == [
        "pkce is required for this client",
    ]

    opt_out_settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        static_client_require_pkce=False,
    )
    opt_out_client, plugin, _belgie_client = _build_fixture(opt_out_settings)
    _update_static_client(plugin, opt_out_settings.client_id, scope="user offline_access")

    no_pkce_success = opt_out_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(opt_out_settings, state="state-no-pkce", with_pkce=False),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert no_pkce_success.status_code == 302
    no_pkce_query = _query(no_pkce_success.headers["location"])
    assert "code" in no_pkce_query

    unexpected_verifier = opt_out_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": opt_out_settings.client_id,
            "client_secret": "static-secret",
            "code": no_pkce_query["code"][0],
            "redirect_uri": str(opt_out_settings.redirect_uris[0]),
            "code_verifier": "verifier",
        },
    )

    assert unexpected_verifier.status_code == 400
    assert unexpected_verifier.json() == {
        "error": "invalid_request",
        "error_description": "code_verifier provided but PKCE was not used in authorization",
    }

    offline_access = opt_out_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(
            opt_out_settings,
            state="state-offline-access",
            scope="user offline_access",
            with_pkce=False,
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert offline_access.status_code == 302
    assert _query(offline_access.headers["location"])["error_description"] == [
        "pkce is required when requesting offline_access scope",
    ]

    pkce_authorize = opt_out_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(opt_out_settings, state="state-with-pkce"),
        headers=_auth_headers(),
        follow_redirects=False,
    )
    pkce_code = _query(pkce_authorize.headers["location"])["code"][0]

    missing_verifier = opt_out_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": opt_out_settings.client_id,
            "client_secret": "static-secret",
            "code": pkce_code,
            "redirect_uri": str(opt_out_settings.redirect_uris[0]),
        },
    )

    assert missing_verifier.status_code == 400
    assert missing_verifier.json() == {
        "error": "invalid_request",
        "error_description": "code_verifier required because PKCE was used in authorization",
    }

    wrong_verifier_authorize = opt_out_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(opt_out_settings, state="state-wrong-verifier"),
        headers=_auth_headers(),
        follow_redirects=False,
    )
    wrong_verifier_code = _query(wrong_verifier_authorize.headers["location"])["code"][0]

    wrong_verifier = opt_out_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": opt_out_settings.client_id,
            "client_secret": "static-secret",
            "code": wrong_verifier_code,
            "redirect_uri": str(opt_out_settings.redirect_uris[0]),
            "code_verifier": "different-verifier",
        },
    )

    assert wrong_verifier.status_code == 400
    assert wrong_verifier.json() == {
        "error": "invalid_grant",
        "error_description": "invalid code_verifier",
    }


def test_dynamic_confidential_client_id_token_uses_server_signing_secret() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        allow_dynamic_client_registration=True,
    )
    client, _plugin, belgie_client = _build_fixture(settings)

    registration = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["http://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
        },
        headers=_auth_headers(),
    )

    assert registration.status_code == 201
    registered_client = registration.json()
    client_secret = registered_client["client_secret"]
    verifier = "dynamic-client-verifier"
    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "http://client.local/callback",
            "scope": "openid user",
            "state": "dynamic-client-state",
            "code_challenge": create_code_challenge(verifier),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    code = _query(authorize.headers["location"])["code"][0]
    token_response = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": registered_client["client_id"],
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": "http://client.local/callback",
            "code_verifier": verifier,
        },
    )

    assert token_response.status_code == 200
    payload = token_response.json()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            payload["id_token"],
            _id_token_signing_key(client_secret),
            algorithms=["HS256"],
            audience=registered_client["client_id"],
            issuer="http://testserver/auth/oauth",
        )

    decoded = jwt.decode(
        payload["id_token"],
        _id_token_signing_key("test-secret"),
        algorithms=["HS256"],
        audience=registered_client["client_id"],
        issuer="http://testserver/auth/oauth",
    )
    assert decoded["sub"] == str(belgie_client.user.id)


def test_consent_flow_preserves_broader_persisted_scopes_after_narrower_reconsent() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        consent_url="/consent-screen",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="user openid")

    initial_authorize = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-consent-wide", scope="user openid"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert initial_authorize.status_code == 302
    initial_state = _query(initial_authorize.headers["location"])["state"][0]
    initial_consent_redirect = client.get(initial_authorize.headers["location"], follow_redirects=False)
    assert initial_consent_redirect.status_code == 302
    assert initial_consent_redirect.headers["location"].startswith("http://testserver/consent-screen?")

    initial_approved = client.post(
        "/auth/oauth/consent",
        data={"state": initial_state, "accept": "true", "scope": "user openid"},
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert initial_approved.status_code == 302
    initial_query = _query(initial_approved.headers["location"])
    initial_token = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "code": initial_query["code"][0],
            "redirect_uri": str(settings.redirect_uris[0]),
            "code_verifier": "verifier",
        },
    )

    assert initial_token.status_code == 200
    assert initial_token.json()["scope"] == "user openid"

    narrowed_authorize = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(
            settings,
            state="state-consent-narrow",
            scope="user",
            prompt="consent",
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert narrowed_authorize.status_code == 302
    narrowed_state = _query(narrowed_authorize.headers["location"])["state"][0]
    narrowed_consent_redirect = client.get(narrowed_authorize.headers["location"], follow_redirects=False)
    assert narrowed_consent_redirect.status_code == 302
    assert narrowed_consent_redirect.headers["location"].startswith("http://testserver/consent-screen?")

    narrowed_approved = client.post(
        "/auth/oauth/consent",
        data={"state": narrowed_state, "accept": "true", "scope": "user"},
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert narrowed_approved.status_code == 302
    narrowed_query = _query(narrowed_approved.headers["location"])
    narrowed_token = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "code": narrowed_query["code"][0],
            "redirect_uri": str(settings.redirect_uris[0]),
            "code_verifier": "verifier",
        },
    )

    assert narrowed_token.status_code == 200
    assert narrowed_token.json()["scope"] == "user"

    repeated_authorize = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-consent-repeat", scope="user openid"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert repeated_authorize.status_code == 302
    assert repeated_authorize.headers["location"].startswith("http://client.local/callback?")
    repeated_query = _query(repeated_authorize.headers["location"])
    repeated_token = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "code": repeated_query["code"][0],
            "redirect_uri": str(settings.redirect_uris[0]),
            "code_verifier": "verifier",
        },
    )

    assert repeated_token.status_code == 200
    assert repeated_token.json()["scope"] == "user openid"


def test_pairwise_subject_is_stable_across_id_token_userinfo_introspection_and_refresh() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        static_client_require_pkce=False,
        pairwise_secret="pairwise-secret",
        enable_end_session=True,
    )
    client, plugin, belgie_client = _build_fixture(settings)
    _update_static_client(
        plugin,
        settings.client_id,
        scope="user openid profile email offline_access",
        subject_type="pairwise",
    )

    authorize = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(
            settings,
            state="state-pairwise",
            scope="openid profile email offline_access",
        ),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    code = _query(authorize.headers["location"])["code"][0]
    token_response = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "client_secret": "static-secret",
            "code": code,
            "redirect_uri": str(settings.redirect_uris[0]),
            "code_verifier": "verifier",
        },
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    id_token = jwt.decode(
        token_payload["id_token"],
        _id_token_signing_key("static-secret"),
        algorithms=["HS256"],
        audience=settings.client_id,
        issuer="http://testserver/auth/oauth",
    )

    userinfo = client.get(
        "/auth/oauth/userinfo",
        headers={"authorization": f"Bearer {token_payload['access_token']}"},
    )
    assert userinfo.status_code == 200

    introspection = client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": settings.client_id,
            "client_secret": "static-secret",
            "token": token_payload["access_token"],
        },
    )
    assert introspection.status_code == 200

    refresh = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.client_id,
            "client_secret": "static-secret",
            "refresh_token": token_payload["refresh_token"],
        },
    )
    assert refresh.status_code == 200
    refresh_payload = refresh.json()
    refreshed_id_token = jwt.decode(
        refresh_payload["id_token"],
        _id_token_signing_key("static-secret"),
        algorithms=["HS256"],
        audience=settings.client_id,
        issuer="http://testserver/auth/oauth",
    )

    refresh_introspection = client.post(
        "/auth/oauth/introspect",
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
    assert introspection.json()["iss"] == "http://testserver/auth/oauth"
