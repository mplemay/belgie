from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import jwt
import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.settings import OAuthServer, OAuthServerResource
from belgie_oauth_server.testing import InMemoryConsent, InMemoryDBConnection
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
    app.include_router(plugin.public(belgie))
    assert plugin.provider is not None
    plugin.provider.static_client = plugin.provider.static_client.model_copy(update={"skip_consent": True})

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


def _decode_id_token(plugin: OAuthServerPlugin, token: str, audience: str) -> dict[str, object]:
    assert plugin.provider is not None
    return jwt.decode(
        token,
        plugin.provider.signing_state.verification_key,
        algorithms=[plugin.provider.signing_state.algorithm],
        audience=audience,
        issuer="http://testserver/auth/oauth",
    )


def _build_settings(**overrides: object) -> OAuthServer:
    settings_overrides = {"default_scopes": ["user"], **overrides}
    return build_oauth_settings(**settings_overrides)


def _trust_dynamic_callback_client(oauth_client) -> bool:
    redirect_uris = {str(uri) for uri in oauth_client.redirect_uris or []}
    grant_types = set(oauth_client.grant_types)
    return (
        redirect_uris == {"https://trusted.local/callback"}
        and oauth_client.token_endpoint_auth_method == "none"  # noqa: S105
        and "authorization_code" in grant_types
    )


def _issue_resource_bound_token(
    client: TestClient,
    plugin: OAuthServerPlugin,
    settings: OAuthServer,
    *,
    state: str,
    scope: str = "openid user",
    verifier: str = "verifier",
) -> dict[str, object]:
    _update_static_client(plugin, settings.client_id, scope=scope)

    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            **_authorize_params(settings, state=state, scope=scope, verifier=verifier),
            "resource": "http://testserver/mcp",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    code = _query(authorize.headers["location"])["code"][0]
    token_request = {
        "grant_type": "authorization_code",
        "client_id": settings.client_id,
        "code": code,
        "redirect_uri": str(settings.redirect_uris[0]),
        "code_verifier": verifier,
    }
    if settings.client_secret is not None:
        token_request["client_secret"] = settings.client_secret.get_secret_value()

    token_response = client.post("/auth/oauth/token", data=token_request)

    assert token_response.status_code == 200
    return token_response.json()


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


def test_authorize_route_is_unavailable_when_authorization_code_grant_is_disabled() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        grant_types=["client_credentials"],
        login_url=None,
        consent_url=None,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-disabled"),
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 404


def test_token_rejects_disabled_grants_before_dispatch() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        grant_types=["client_credentials"],
        login_url=None,
        consent_url=None,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "unsupported_grant_type",
        "error_description": "unsupported grant_type authorization_code",
    }


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
    _update_static_client(plugin, settings.client_id, scope="user openid", skip_consent=False)

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
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, skip_consent=False)

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


def test_register_coerces_unauthenticated_clients_to_public() -> None:
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
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )

    assert confidential.status_code == 201
    confidential_payload = confidential.json()
    assert confidential_payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert confidential_payload["grant_types"] == ["authorization_code"]
    assert "client_secret" not in confidential_payload
    assert confidential_payload["require_pkce"] is True

    omitted_auth_method = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
        },
    )

    assert omitted_auth_method.status_code == 201
    omitted_payload = omitted_auth_method.json()
    assert omitted_payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert omitted_payload["grant_types"] == ["authorization_code"]
    assert "client_secret" not in omitted_payload
    assert omitted_payload["require_pkce"] is True

    confidential_basic = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )

    assert confidential_basic.status_code == 201
    confidential_basic_payload = confidential_basic.json()
    assert confidential_basic_payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert confidential_basic_payload["grant_types"] == ["authorization_code"]
    assert "client_secret" not in confidential_basic_payload
    assert confidential_basic_payload["require_pkce"] is True

    web_type = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
        },
    )

    assert web_type.status_code == 201
    web_type_payload = web_type.json()
    assert web_type_payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert "type" not in web_type_payload
    assert "client_secret" not in web_type_payload

    public = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "user",
        },
    )

    assert public.status_code == 201
    public_payload = public.json()
    assert public_payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert "client_secret" not in public_payload
    assert public_payload["require_pkce"] is True


def test_register_defaults_authenticated_confidential_clients_to_client_secret_basic() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/register",
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


def test_register_rejects_client_supplied_skip_consent_even_for_trusted_clients() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        trusted_client_resolver=_trust_dynamic_callback_client,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://trusted.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "skip_consent": True,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_client_metadata",
        "error_description": "skip_consent cannot be set during dynamic client registration",
    }


def test_trusted_unauthenticated_dcr_public_client_skips_consent() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        trusted_client_resolver=_trust_dynamic_callback_client,
    )
    client, plugin, belgie_client = _build_fixture(settings)

    registration = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://trusted.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "openid user",
        },
    )

    assert registration.status_code == 201
    registered_client = registration.json()
    assert registered_client["skip_consent"] is True

    verifier = "trusted-dynamic-public-verifier"
    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "https://trusted.local/callback",
            "scope": "openid user",
            "state": "trusted-dynamic-public-state",
            "code_challenge": create_code_challenge(verifier),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    assert authorize.headers["location"].startswith("https://trusted.local/callback?")
    code = _query(authorize.headers["location"])["code"][0]
    token_response = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": registered_client["client_id"],
            "code": code,
            "redirect_uri": "https://trusted.local/callback",
            "code_verifier": verifier,
        },
    )

    assert token_response.status_code == 200
    payload = token_response.json()
    assert payload["scope"] == "openid user"
    decoded = _decode_id_token(plugin, payload["id_token"], registered_client["client_id"])
    assert decoded["sub"] == str(belgie_client.user.id)


def test_untrusted_unauthenticated_dcr_public_client_still_requires_consent() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        consent_url="/consent-screen",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        trusted_client_resolver=_trust_dynamic_callback_client,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    registration = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "openid user",
        },
    )

    assert registration.status_code == 201
    registered_client = registration.json()
    assert registered_client["skip_consent"] is False

    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "https://client.local/callback",
            "scope": "openid user",
            "state": "untrusted-dynamic-public-state",
            "code_challenge": create_code_challenge("untrusted-dynamic-public-verifier"),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    assert authorize.headers["location"].startswith("http://testserver/auth/oauth/login?")
    state = _query(authorize.headers["location"])["state"][0]
    consent_redirect = client.get(authorize.headers["location"], follow_redirects=False)

    assert consent_redirect.status_code == 302
    assert consent_redirect.headers["location"].startswith("http://testserver/consent-screen?")
    assert _query(consent_redirect.headers["location"])["return_to"] == [
        f"http://testserver/auth/oauth/consent?state={state}",
    ]


def test_existing_dynamic_client_uses_trusted_policy_without_reconsent() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
    )
    client, plugin, _belgie_client = _build_fixture(settings)

    registration = client.post(
        "/auth/oauth/register",
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

    plugin.settings.trusted_client_resolver = _trust_dynamic_callback_client

    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "https://trusted.local/callback",
            "scope": "openid user",
            "state": "trusted-dynamic-existing-state",
            "code_challenge": create_code_challenge("trusted-dynamic-existing-verifier"),
            "code_challenge_method": "S256",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert authorize.status_code == 302
    assert authorize.headers["location"].startswith("https://trusted.local/callback?")


def test_metadata_prioritizes_public_token_auth_when_anonymous_registration_is_enabled() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    assert response.json()["token_endpoint_auth_methods_supported"] == [
        "none",
        "client_secret_basic",
        "client_secret_post",
    ]


def test_metadata_advertises_public_token_auth_when_authenticated_registration_can_create_public_clients() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    assert response.json()["token_endpoint_auth_methods_supported"] == [
        "none",
        "client_secret_basic",
        "client_secret_post",
    ]


def test_metadata_advertises_public_token_auth_for_public_static_client() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=False,
        client_secret=None,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    assert response.json()["token_endpoint_auth_methods_supported"] == [
        "none",
        "client_secret_basic",
        "client_secret_post",
    ]


def test_register_rejects_unsupported_auth_method() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "private_key_jwt",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_request",
        "error_description": "unsupported token_endpoint_auth_method: private_key_jwt",
    }


def test_register_rejects_grant_types_disabled_by_server() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        grant_types=["client_credentials"],
        login_url=None,
        consent_url=None,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "grant_types": ["authorization_code"],
            "type": "web",
        },
        headers=_auth_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_client_metadata",
        "error_description": "unsupported grant_type authorization_code",
    }


def test_register_allows_public_clients_with_configured_resource_scopes() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        resources=[OAuthServerResource(prefix="/mcp", scopes=["user", "files:read"])],
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
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


def test_register_preserves_success_headers_with_response_model_serialization() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "user",
        },
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    payload = response.json()
    assert payload["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert "client_secret" not in payload


def test_unauthenticated_dcr_public_client_completes_authorize_and_token_exchange() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
    )
    client, plugin, belgie_client = _build_fixture(settings)

    registration = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
        },
    )

    assert registration.status_code == 201
    registered_client = registration.json()
    assert registered_client["token_endpoint_auth_method"] == "none"  # noqa: S105
    assert "client_secret" not in registered_client
    assert "type" not in registered_client

    _grant_consent(plugin, registered_client["client_id"], belgie_client.user.id, ["openid", "user"])
    verifier = "dynamic-public-verifier"
    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "https://client.local/callback",
            "scope": "openid user",
            "state": "dynamic-public-state",
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
            "code": code,
            "redirect_uri": "https://client.local/callback",
            "code_verifier": verifier,
        },
    )

    assert token_response.status_code == 200
    payload = token_response.json()
    assert payload["access_token"]
    assert payload["scope"] == "openid user"
    decoded = _decode_id_token(plugin, payload["id_token"], registered_client["client_id"])
    assert decoded["sub"] == str(belgie_client.user.id)


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


def test_dynamic_confidential_client_id_token_uses_server_signing_key() -> None:
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
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "openid user",
        },
        headers=_auth_headers(),
    )

    assert registration.status_code == 201
    registered_client = registration.json()
    client_secret = registered_client["client_secret"]
    _grant_consent(_plugin, registered_client["client_id"], belgie_client.user.id, ["openid", "user"])
    verifier = "dynamic-client-verifier"
    authorize = client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "https://client.local/callback",
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
            "redirect_uri": "https://client.local/callback",
            "code_verifier": verifier,
        },
    )

    assert token_response.status_code == 200
    payload = token_response.json()
    decoded = _decode_id_token(_plugin, payload["id_token"], registered_client["client_id"])
    assert decoded["sub"] == str(belgie_client.user.id)

    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(
            payload["id_token"],
            "test-secret",
            algorithms=["HS256"],
            audience=registered_client["client_id"],
            issuer="http://testserver/auth/oauth",
        )


def test_consent_flow_preserves_broader_persisted_scopes_after_narrower_reconsent() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        consent_url="/consent-screen",
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    _update_static_client(plugin, settings.client_id, scope="user openid", skip_consent=False)

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
    id_token = _decode_id_token(plugin, token_payload["id_token"], settings.client_id)

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
    refreshed_id_token = _decode_id_token(plugin, refresh_payload["id_token"], settings.client_id)

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


def test_introspect_missing_token_returns_modeled_error_body() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    response = client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": settings.client_id,
            "client_secret": "static-secret",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"active": False}


def test_revoked_signed_access_token_fails_userinfo_and_introspection() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        resources=[OAuthServerResource(prefix="/mcp", scopes=["user"])],
    )
    client, plugin, _belgie_client = _build_fixture(settings)

    token_payload = _issue_resource_bound_token(client, plugin, settings, state="state-revoked-jwt")
    assert token_payload["access_token"].count(".") == 2

    revoke = client.post(
        "/auth/oauth/revoke",
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
        "/auth/oauth/userinfo",
        headers={"authorization": f"Bearer {token_payload['access_token']}"},
    )

    assert userinfo.status_code == 401
    assert userinfo.json() == {"error": "invalid_token"}

    introspection = client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": settings.client_id,
            "client_secret": "static-secret",
            "token": token_payload["access_token"],
        },
    )

    assert introspection.status_code == 200
    assert introspection.json() == {"active": False}


def test_introspect_rejects_tokens_issued_to_different_confidential_client() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_secret="static-secret",
        allow_dynamic_client_registration=True,
        resources=[OAuthServerResource(prefix="/mcp", scopes=["user"])],
    )
    client, plugin, _belgie_client = _build_fixture(settings)

    token_payload = _issue_resource_bound_token(client, plugin, settings, state="state-other-client-introspection")
    registration = client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["https://other-client.local/callback"],
            "type": "web",
        },
        headers=_auth_headers(),
    )

    assert registration.status_code == 201
    confidential_client = registration.json()
    assert confidential_client["client_secret"]

    introspection = client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": confidential_client["client_id"],
            "client_secret": confidential_client["client_secret"],
            "token": token_payload["access_token"],
        },
    )

    assert introspection.status_code == 200
    assert introspection.json() == {"active": False}


def test_patch_client_rejects_invalid_merged_metadata() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/oauth/clients",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "user",
        },
        headers=_auth_headers(),
    )

    assert created.status_code == 201
    patched = client.patch(
        f"/auth/oauth/clients/{created.json()['client_id']}",
        json={"redirect_uris": ["not-a-uri"]},
        headers=_auth_headers(),
    )

    assert patched.status_code == 400
    assert patched.json()["error"] == "invalid_request"
    assert "redirect_uris" in patched.json()["error_description"]


def test_patch_client_rejects_public_to_confidential_transition_without_secret() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/oauth/clients",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "none",
            "type": "native",
            "scope": "user",
        },
        headers=_auth_headers(),
    )

    assert created.status_code == 201
    client_id = created.json()["client_id"]

    patched = client.patch(
        f"/auth/oauth/clients/{client_id}",
        json={"token_endpoint_auth_method": "client_secret_post", "type": "web"},
        headers=_auth_headers(),
    )

    assert patched.status_code == 400
    assert patched.json() == {
        "error": "invalid_request",
        "error_description": "confidential clients require a stored client secret",
    }
    reloaded_client = client.get(
        f"/auth/oauth/clients/{client_id}",
        headers=_auth_headers(),
    )

    assert reloaded_client.status_code == 200
    assert reloaded_client.json()["token_endpoint_auth_method"] == "none"  # noqa: S105


def test_authorize_allows_loopback_port_mismatch_only_for_public_clients() -> None:
    public_settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://localhost/callback"],
        client_id="test-client",
    )
    public_client, _plugin, _belgie_client = _build_fixture(public_settings)

    public_response = public_client.get(
        "/auth/oauth/authorize",
        params={
            **_authorize_params(public_settings, state="state-public-loopback"),
            "redirect_uri": "http://localhost:43123/callback",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert public_response.status_code == 302
    assert public_response.headers["location"].startswith("http://localhost:43123/callback?")
    assert "code" in _query(public_response.headers["location"])

    confidential_settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://localhost/callback"],
        client_id="test-client",
        client_secret="static-secret",
    )
    confidential_client, _plugin, _belgie_client = _build_fixture(confidential_settings)

    confidential_response = confidential_client.get(
        "/auth/oauth/authorize",
        params={
            **_authorize_params(confidential_settings, state="state-confidential-loopback"),
            "redirect_uri": "http://localhost:43123/callback",
        },
        headers=_auth_headers(),
        follow_redirects=False,
    )

    assert confidential_response.status_code == 400
    assert confidential_response.json() == {
        "error": "invalid_request",
        "error_description": "Redirect URI 'http://localhost:43123/callback' not registered for client",
    }


def test_client_management_secret_responses_are_not_cacheable() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    created = client.post(
        "/auth/oauth/clients",
        json={
            "redirect_uris": ["https://client.local/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "type": "web",
            "scope": "user",
        },
        headers=_auth_headers(),
    )

    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    assert created.headers["pragma"] == "no-cache"
    created_payload = created.json()
    assert created_payload["client_secret"]

    rotated = client.post(
        f"/auth/oauth/clients/{created_payload['client_id']}/rotate-secret",
        headers=_auth_headers(),
    )

    assert rotated.status_code == 200
    assert rotated.headers["cache-control"] == "no-store"
    assert rotated.headers["pragma"] == "no-cache"
    assert rotated.json()["client_secret"] != created_payload["client_secret"]


def test_consent_management_requires_action_specific_delegated_privileges() -> None:
    reference_id = "workspace-123"
    delegated_actions = {"read"}

    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_reference_resolver=lambda _individual_id, _session_id: reference_id,
        client_privileges=lambda action, _individual_id, _session_id, candidate_reference_id: (
            candidate_reference_id == reference_id and action in delegated_actions
        ),
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    assert plugin.provider is not None
    adapter = plugin.provider.adapter

    delegated_consent_individual_id = uuid4()
    consent = InMemoryConsent(
        client_id=settings.client_id,
        individual_id=delegated_consent_individual_id,
        reference_id=reference_id,
        scopes=["user"],
    )
    adapter.consents[(settings.client_id, delegated_consent_individual_id, reference_id)] = consent

    fetched = client.get(
        f"/auth/oauth/consents/{consent.id}",
        headers=_auth_headers(),
    )

    assert fetched.status_code == 200
    assert fetched.json()["reference_id"] == reference_id

    patched = client.patch(
        f"/auth/oauth/consents/{consent.id}",
        json={"scopes": ["openid"]},
        headers=_auth_headers(),
    )

    assert patched.status_code == 403
    assert patched.json() == {"error": "access_denied"}

    deleted = client.delete(
        f"/auth/oauth/consents/{consent.id}",
        headers=_auth_headers(),
    )

    assert deleted.status_code == 403
    assert deleted.json() == {"error": "access_denied"}

    assert adapter.consents[(settings.client_id, delegated_consent_individual_id, reference_id)].scopes == ["user"]


def test_consent_management_allows_delegated_write_privileges() -> None:
    reference_id = "workspace-123"
    delegated_actions = {"read", "update", "delete"}

    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        client_reference_resolver=lambda _individual_id, _session_id: reference_id,
        client_privileges=lambda action, _individual_id, _session_id, candidate_reference_id: (
            candidate_reference_id == reference_id and action in delegated_actions
        ),
    )
    client, plugin, _belgie_client = _build_fixture(settings)
    assert plugin.provider is not None
    adapter = plugin.provider.adapter

    delegated_consent_individual_id = uuid4()
    consent = InMemoryConsent(
        client_id=settings.client_id,
        individual_id=delegated_consent_individual_id,
        reference_id=reference_id,
        scopes=["user"],
    )
    adapter.consents[(settings.client_id, delegated_consent_individual_id, reference_id)] = consent

    patched = client.patch(
        f"/auth/oauth/consents/{consent.id}",
        json={"scopes": ["user", "openid"]},
        headers=_auth_headers(),
    )

    assert patched.status_code == 200
    assert patched.json()["scopes"] == ["user", "openid"]
    assert adapter.consents[(settings.client_id, delegated_consent_individual_id, reference_id)].scopes == [
        "user",
        "openid",
    ]

    deleted = client.delete(
        f"/auth/oauth/consents/{consent.id}",
        headers=_auth_headers(),
    )

    assert deleted.status_code == 200
    assert deleted.json() == {}
    assert (settings.client_id, delegated_consent_individual_id, reference_id) not in adapter.consents


def test_authorize_rate_limit_ignores_x_forwarded_for() -> None:
    settings = _build_settings(
        base_url="http://testserver",
        redirect_uris=["http://client.local/callback"],
        client_id="test-client",
        rate_limit={"authorize": {"window": 60, "max": 1}},
    )
    client, _plugin, _belgie_client = _build_fixture(settings)

    first = client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(settings, state="state-rate-limit-1"),
        headers={"x-forwarded-for": "203.0.113.1"},
        follow_redirects=False,
    )
    second = client.get(
        "/auth/oauth/authorize",
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
