from belgie_core.core.belgie import Belgie
from belgie_oauth_server import OAuthServer, OAuthServerResource
from belgie_oauth_server.metadata import _ROOT_OAUTH_METADATA_PATH, _ROOT_OPENID_METADATA_PATH
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

AUTH_BASE_URL = "http://testserver/auth/oauth"
RESOURCE_BASE_URL = "http://testserver/mcp"


def test_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/auth/oauth/.well-known/oauth-authorization-server")
    assert response.status_code == 200

    payload = response.json()
    assert payload["issuer"] == AUTH_BASE_URL
    assert payload["authorization_endpoint"] == f"{AUTH_BASE_URL}/authorize"
    assert payload["token_endpoint"] == f"{AUTH_BASE_URL}/token"
    assert payload["registration_endpoint"] == f"{AUTH_BASE_URL}/register"
    assert payload["revocation_endpoint"] == f"{AUTH_BASE_URL}/revoke"
    assert payload["introspection_endpoint"] == f"{AUTH_BASE_URL}/introspect"
    assert payload["grant_types_supported"] == ["authorization_code", "client_credentials", "refresh_token"]
    assert payload["response_modes_supported"] == ["query"]
    assert payload["token_endpoint_auth_methods_supported"] == [
        "none",
        "client_secret_basic",
        "client_secret_post",
    ]
    assert payload["revocation_endpoint_auth_methods_supported"] == ["client_secret_post", "client_secret_basic"]
    assert payload["introspection_endpoint_auth_methods_supported"] == ["client_secret_post", "client_secret_basic"]


def test_metadata_alias_endpoint(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-authorization-server/auth/oauth")
    assert response.status_code == 200

    payload = response.json()
    assert payload["issuer"] == AUTH_BASE_URL
    assert payload["authorization_endpoint"] == f"{AUTH_BASE_URL}/authorize"
    assert payload["token_endpoint"] == f"{AUTH_BASE_URL}/token"
    assert payload["registration_endpoint"] == f"{AUTH_BASE_URL}/register"
    assert payload["revocation_endpoint"] == f"{AUTH_BASE_URL}/revoke"
    assert payload["introspection_endpoint"] == f"{AUTH_BASE_URL}/introspect"


def test_openid_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/auth/oauth/.well-known/openid-configuration")
    assert response.status_code == 200

    payload = response.json()
    assert payload["issuer"] == AUTH_BASE_URL
    assert payload["userinfo_endpoint"] == f"{AUTH_BASE_URL}/userinfo"
    assert payload["end_session_endpoint"] == f"{AUTH_BASE_URL}/end-session"
    assert payload["id_token_signing_alg_values_supported"] == ["RS256"]
    assert payload["response_modes_supported"] == ["query"]


def test_openid_metadata_root_fallback(client: TestClient) -> None:
    response = client.get(_ROOT_OPENID_METADATA_PATH)
    assert response.status_code == 200
    assert response.json()["issuer"] == AUTH_BASE_URL


def test_protected_resource_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200

    payload = response.json()
    assert payload["resource"] == RESOURCE_BASE_URL
    assert payload["authorization_servers"] == [AUTH_BASE_URL]
    assert payload["scopes_supported"] == ["user"]


def test_protected_resource_metadata_endpoint_preserves_trailing_slash_canonical_path(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = oauth_settings.model_copy(
        update={
            "client_secret": SecretStr("test-secret"),
            "resources": [OAuthServerResource(prefix="/mcp/", scopes=["user"])],
        },
    )
    belgie_instance.add_plugin(settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp/", follow_redirects=False)
        alias_response = client.get("/.well-known/oauth-protected-resource/mcp", follow_redirects=False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "http://testserver/mcp/"
    assert payload["authorization_servers"] == [AUTH_BASE_URL]
    assert payload["scopes_supported"] == ["user"]
    assert alias_response.status_code == 307
    assert alias_response.headers["location"] == "http://testserver/.well-known/oauth-protected-resource/mcp/"


def test_protected_resource_metadata_root_fallback(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200

    payload = response.json()
    assert payload["resource"] == RESOURCE_BASE_URL
    assert payload["authorization_servers"] == [AUTH_BASE_URL]
    assert payload["scopes_supported"] == ["user"]


def test_protected_resource_metadata_absent_when_resource_server_unset(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = oauth_settings.model_copy(update={"client_secret": SecretStr("test-secret"), "resources": None})
    belgie_instance.add_plugin(settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 404

        root_response = client.get("/.well-known/oauth-protected-resource")
        assert root_response.status_code == 404


def test_oauth_metadata_root_fallback(client: TestClient) -> None:
    response = client.get(_ROOT_OAUTH_METADATA_PATH)
    assert response.status_code == 200

    payload = response.json()
    assert payload["issuer"] == AUTH_BASE_URL
    assert payload["authorization_endpoint"] == f"{AUTH_BASE_URL}/authorize"
    assert payload["token_endpoint"] == f"{AUTH_BASE_URL}/token"
    assert payload["registration_endpoint"] == f"{AUTH_BASE_URL}/register"
    assert payload["revocation_endpoint"] == f"{AUTH_BASE_URL}/revoke"
    assert payload["introspection_endpoint"] == f"{AUTH_BASE_URL}/introspect"


def test_oauth_metadata_root_fallback_absent_when_disabled(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = oauth_settings.model_copy(
        update={
            "client_secret": SecretStr("test-secret"),
            "include_root_oauth_metadata_fallback": False,
        },
    )
    belgie_instance.add_plugin(settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        # Root fallback should 404 when disabled
        response = client.get(_ROOT_OAUTH_METADATA_PATH)
        assert response.status_code == 404

        # Path-based endpoint should still work
        response = client.get("/.well-known/oauth-authorization-server/auth/oauth")
        assert response.status_code == 200


def test_openid_metadata_root_fallback_absent_when_disabled(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = oauth_settings.model_copy(
        update={
            "client_secret": SecretStr("test-secret"),
            "include_root_openid_metadata_fallback": False,
        },
    )
    belgie_instance.add_plugin(settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        response = client.get(_ROOT_OPENID_METADATA_PATH)
        assert response.status_code == 404
        response = client.get("/auth/oauth/.well-known/openid-configuration")
        assert response.status_code == 200


def test_metadata_endpoints_omit_authorization_endpoint_when_client_credentials_only(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = oauth_settings.model_copy(
        update={
            "grant_types": ["client_credentials"],
            "login_url": None,
            "consent_url": None,
        },
    )
    belgie_instance.add_plugin(settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        for path in (
            "/auth/oauth/.well-known/oauth-authorization-server",
            "/.well-known/oauth-authorization-server/auth/oauth",
            "/auth/oauth/.well-known/openid-configuration",
            "/.well-known/openid-configuration",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert "authorization_endpoint" not in response.json()

        response = client.get("/auth/oauth/authorize", follow_redirects=False)
        assert response.status_code == 404
