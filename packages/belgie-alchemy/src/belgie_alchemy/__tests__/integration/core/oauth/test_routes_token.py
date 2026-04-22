from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
from belgie_oauth_server.provider import AuthorizationParams
from belgie_oauth_server.utils import create_code_challenge
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from joserfc import jwt
from joserfc.errors import BadSignatureError
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from belgie_alchemy.__tests__.integration.core.oauth.conftest import ensure_oauth_test_client_seeded

BEARER = "Bearer"


async def _create_authorization_code(
    oauth_plugin,
    oauth_settings,
    code_verifier: str,
    *,
    belgie_instance,
    db_session,
    create_individual_session,
    scopes: list[str] | None = None,
    resource: str | None = None,
) -> str:
    provider = oauth_plugin._provider
    oauth_client = await provider.get_client("test-client")
    session_id = await create_individual_session(belgie_instance, db_session, f"{code_verifier}@test.com")
    session = await belgie_instance.session_manager.get_session(db_session, UUID(session_id))
    assert session is not None
    params = AuthorizationParams(
        state="state-token",
        scopes=scopes or list(oauth_settings.default_scopes),
        code_challenge=create_code_challenge(code_verifier),
        redirect_uri="http://localhost/callback",
        redirect_uri_provided_explicitly=True,
        resource=resource,
        individual_id=str(session.individual_id),
        session_id=session_id,
    )
    await provider.authorize(oauth_client, params)
    redirect_url = await provider.issue_authorization_code("state-token")
    return parse_qs(urlparse(redirect_url).query)["code"][0]


async def _create_refresh_token(
    async_client,
    oauth_settings,
    oauth_plugin,
    update_oauth_test_client,
    belgie_instance,
    db_session,
    create_individual_session,
    *,
    resource: str | None = None,
) -> str:
    await update_oauth_test_client(scope=" ".join([*oauth_settings.default_scopes, "offline_access"]))
    code_verifier = "refresh-verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        belgie_instance=belgie_instance,
        db_session=db_session,
        create_individual_session=create_individual_session,
        scopes=[*oauth_settings.default_scopes, "offline_access"],
        resource=resource,
    )
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )
    assert response.status_code == 200
    return response.json()["refresh_token"]


@pytest.mark.asyncio
async def test_token_missing_grant_type(async_client) -> None:
    response = await async_client.post("/auth/oauth2/token", data={})
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


@pytest.mark.asyncio
async def test_token_unsupported_grant_type(async_client) -> None:
    response = await async_client.post("/auth/oauth2/token", data={"grant_type": "urn:custom"})
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


@pytest.mark.asyncio
async def test_token_authorization_code_missing_code(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_token_authorization_code_invalid_client(async_client) -> None:
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "wrong",
            "client_secret": "bad",
            "code": "nope",
            "code_verifier": "verifier",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_token_authorization_code_invalid_client_secret(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        "verifier",
        belgie_instance=belgie_instance,
        db_session=db_session,
        create_individual_session=create_individual_session,
    )
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "wrong",
            "code": code,
            "code_verifier": "verifier",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_token_authorization_code_success_no_offline_access(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    code_verifier = "verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        belgie_instance=belgie_instance,
        db_session=db_session,
        create_individual_session=create_individual_session,
    )

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == BEARER
    assert payload["scope"] == " ".join(oauth_settings.default_scopes)
    assert payload.get("refresh_token") is None


@pytest.mark.asyncio
async def test_token_authorization_code_success_with_offline_access_issues_refresh(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    code_verifier = "offline-verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        belgie_instance=belgie_instance,
        db_session=db_session,
        create_individual_session=create_individual_session,
        scopes=[*oauth_settings.default_scopes, "offline_access"],
    )

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refresh_token"] is not None
    assert payload["scope"] == " ".join([*oauth_settings.default_scopes, "offline_access"])


@pytest.mark.asyncio
async def test_token_authorization_code_accepts_basic_auth(
    async_client,
    oauth_settings,
    oauth_plugin,
    basic_auth_header,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    code_verifier = "basic-verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        belgie_instance=belgie_instance,
        db_session=db_session,
        create_individual_session=create_individual_session,
    )
    auth_header = basic_auth_header("test-client", "test-secret")

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
        headers={"authorization": auth_header},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == BEARER


@pytest.mark.asyncio
async def test_token_authorization_code_rejects_resource_without_bound_resource(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    code_verifier = "resource-missing-verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        belgie_instance=belgie_instance,
        db_session=db_session,
        create_individual_session=create_individual_session,
    )

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
            "resource": "http://testserver/mcp",
        },
    )

    assert response.status_code == 200
    access_token = response.json()["access_token"]
    stored_access_token = await oauth_plugin._provider.load_access_token(access_token)
    assert stored_access_token is not None
    assert stored_access_token.resource == "http://testserver/mcp"


@pytest.mark.asyncio
async def test_token_authorization_code_rejects_mismatched_bound_resource(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    code_verifier = "resource-mismatch-verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        belgie_instance=belgie_instance,
        db_session=db_session,
        create_individual_session=create_individual_session,
        resource="http://testserver/mcp",
    )

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
            "resource": "http://testserver/other",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_target"


@pytest.mark.asyncio
async def test_token_authorization_code_accepts_resource_without_trailing_slash_for_trailing_slash_configuration(
    belgie_instance,
    db_session,
    oauth_settings,
    create_individual_session,
) -> None:
    settings = oauth_settings.model_copy(
        update={
            "fallback_signing_secret": SecretStr("test-secret"),
            "valid_audiences": ["http://testserver/mcp/"],
        },
    )
    oauth_plugin = belgie_instance.add_plugin(settings)
    await ensure_oauth_test_client_seeded(belgie_instance, db_session, settings, oauth_plugin)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    assert oauth_plugin.provider is not None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await create_individual_session(belgie_instance, db_session, "token-trailing-resource@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)

        code_verifier = "trailing-resource-verifier"
        authorize_response = await client.get(
            "/auth/oauth2/authorize",
            params={
                "response_type": "code",
                "client_id": "test-client",
                "redirect_uri": "http://localhost/callback",
                "code_challenge": create_code_challenge(code_verifier),
                "code_challenge_method": "S256",
                "state": "state-trailing-resource",
                "resource": "http://testserver/mcp",
            },
            follow_redirects=False,
        )
        assert authorize_response.status_code == 302
        code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][0]

        token_response = await client.post(
            "/auth/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "code": code,
                "redirect_uri": "http://localhost/callback",
                "code_verifier": code_verifier,
                "resource": "http://testserver/mcp",
            },
        )

    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]
    stored_access_token = await oauth_plugin._provider.load_access_token(access_token)
    assert stored_access_token is not None
    assert stored_access_token.resource == "http://testserver/mcp/"


@pytest.mark.asyncio
async def test_token_authorization_code_issues_id_token_for_confidential_openid_client(
    async_client,
    oauth_settings,
    belgie_instance,
    db_session,
    create_individual_session,
    update_oauth_test_client,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "openid-confidential@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)
    await update_oauth_test_client(scope="openid profile email")

    code_verifier = "openid-confidential-verifier"
    authorize_response = await async_client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": "http://localhost/callback",
            "code_challenge": create_code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "scope": "openid profile email",
            "state": "openid-confidential-state",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][0]

    token_response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )

    assert token_response.status_code == 200
    assert token_response.json().get("id_token") is not None


@pytest.mark.asyncio
async def test_token_authorization_code_issues_id_token_for_public_client(
    async_client,
    belgie_instance,
    db_session,
    create_individual_session,
    seed_client,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "openid-public@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)
    await seed_client(
        client_id="public-openid",
        redirect_uris=["http://localhost/callback"],
        scope="openid profile email",
        token_endpoint_auth_method="none",
    )

    code_verifier = "openid-public-verifier"
    authorize_response = await async_client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": "public-openid",
            "redirect_uri": "http://localhost/callback",
            "code_challenge": create_code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "scope": "openid profile email",
            "state": "openid-public-state",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][0]

    token_response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "public-openid",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )

    assert token_response.status_code == 200
    assert token_response.json().get("id_token") is not None


@pytest.mark.asyncio
async def test_token_authorization_code_dynamic_confidential_client_uses_client_secret(
    async_client,
    belgie_instance,
    db_session,
    create_individual_session,
    register_dynamic_client,
    seed_consent,
    oauth_plugin,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "openid-dynamic@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)
    dynamic_client = await register_dynamic_client(
        redirect_uris=["http://localhost/callback"],
        token_endpoint_auth_method="client_secret_post",
        type="web",
        scope="openid profile email",
    )
    await seed_consent(
        client_id=dynamic_client.client_id,
        session_id=session_id,
        scopes=["openid", "profile", "email"],
    )

    assert dynamic_client.client_secret is not None
    code_verifier = "openid-dynamic-verifier"
    authorize_response = await async_client.get(
        "/auth/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": dynamic_client.client_id,
            "redirect_uri": "http://localhost/callback",
            "code_challenge": create_code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "scope": "openid profile email",
            "state": "openid-dynamic-state",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][0]

    token_response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": dynamic_client.client_id,
            "client_secret": dynamic_client.client_secret,
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )

    assert token_response.status_code == 200
    id_token = token_response.json()["id_token"]
    provider = oauth_plugin.provider
    assert provider is not None
    decoded = provider.signing_state.decode(
        id_token,
        audience=dynamic_client.client_id,
        issuer="http://testserver/auth",
    )
    assert decoded["sub"]

    wrong_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_public_key = wrong_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(BadSignatureError):
        jwt.decode(
            id_token,
            key=RSAKey.import_key(wrong_public_key),
            algorithms=[provider.signing_state.algorithm],
        )


@pytest.mark.asyncio
async def test_token_refresh_token_success_rotates_and_narrows_scope(
    async_client,
    oauth_settings,
    oauth_plugin,
    update_oauth_test_client,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    old_refresh_token = await _create_refresh_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        update_oauth_test_client,
        belgie_instance,
        db_session,
        create_individual_session,
    )

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "refresh_token": old_refresh_token,
            "scope": " ".join(oauth_settings.default_scopes),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == " ".join(oauth_settings.default_scopes)
    assert payload["refresh_token"] is not None
    assert payload["refresh_token"] != old_refresh_token

    old_refresh_response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "refresh_token": old_refresh_token,
        },
    )
    assert old_refresh_response.status_code == 400
    assert old_refresh_response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_refresh_token_rejects_scope_escalation(
    async_client,
    oauth_settings,
    oauth_plugin,
    update_oauth_test_client,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    refresh_token = await _create_refresh_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        update_oauth_test_client,
        belgie_instance,
        db_session,
        create_individual_session,
    )
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "refresh_token": refresh_token,
            "scope": "admin",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"


@pytest.mark.asyncio
async def test_token_refresh_token_rejects_mismatched_resource(
    async_client,
    oauth_settings,
    oauth_plugin,
    update_oauth_test_client,
    belgie_instance,
    db_session,
    create_individual_session,
) -> None:
    refresh_token = await _create_refresh_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        update_oauth_test_client,
        belgie_instance,
        db_session,
        create_individual_session,
        resource="http://testserver/mcp",
    )
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "refresh_token": refresh_token,
            "resource": "http://testserver/other",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_target"


@pytest.mark.asyncio
async def test_token_client_credentials_success_post_auth(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "scope": " ".join(oauth_settings.default_scopes),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == BEARER
    assert payload["scope"] == " ".join(oauth_settings.default_scopes)
    assert payload.get("refresh_token") is None


@pytest.mark.asyncio
async def test_token_client_credentials_success_basic_auth(
    async_client,
    oauth_settings,
    basic_auth_header,
) -> None:
    auth_header = basic_auth_header("test-client", "test-secret")

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "scope": " ".join(oauth_settings.default_scopes),
        },
        headers={"authorization": auth_header},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == BEARER


@pytest.mark.asyncio
async def test_token_client_credentials_rejects_unknown_scope(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "scope": "admin",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"


@pytest.mark.asyncio
async def test_token_client_credentials_rejects_mismatched_resource(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "scope": " ".join(oauth_settings.default_scopes),
            "resource": "http://testserver/other",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_target"


@pytest.mark.asyncio
async def test_token_client_credentials_rejects_public_client(
    async_client,
    seed_client,
) -> None:
    await seed_client(
        client_id="public-client",
        redirect_uris=["http://localhost/callback"],
        scope="user",
        token_endpoint_auth_method="none",
    )

    response = await async_client.post(
        "/auth/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "public-client",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
