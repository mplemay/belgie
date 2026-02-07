from belgie_core.core.belgie import Belgie
from belgie_oauth_server import OAuthPlugin, OAuthSettings
from belgie_oauth_server.metadata import _ROOT_OAUTH_METADATA_PATH
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


def test_protected_resource_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200

    payload = response.json()
    assert payload["resource"] == RESOURCE_BASE_URL
    assert payload["authorization_servers"] == [AUTH_BASE_URL]
    assert payload["scopes_supported"] == ["user"]


def test_protected_resource_metadata_root_fallback(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200

    payload = response.json()
    assert payload["resource"] == RESOURCE_BASE_URL
    assert payload["authorization_servers"] == [AUTH_BASE_URL]
    assert payload["scopes_supported"] == ["user"]


def test_protected_resource_metadata_absent_when_resource_server_unset(
    belgie_instance: Belgie,
) -> None:
    settings = OAuthSettings(
        base_url="http://testserver",
        route_prefix="/oauth",
        login_url="/login/google",
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        redirect_uris=["http://testserver/callback"],
        default_scope="user",
    )
    belgie_instance.add_plugin(OAuthPlugin, settings)

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
) -> None:
    settings = OAuthSettings(
        base_url="http://testserver",
        route_prefix="/oauth",
        login_url="/login/google",
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        redirect_uris=["http://testserver/callback"],
        default_scope="user",
        include_root_oauth_metadata_fallback=False,
    )
    belgie_instance.add_plugin(OAuthPlugin, settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        # Root fallback should 404 when disabled
        response = client.get(_ROOT_OAUTH_METADATA_PATH)
        assert response.status_code == 404

        # Path-based endpoint should still work
        response = client.get("/.well-known/oauth-authorization-server/auth/oauth")
        assert response.status_code == 200
