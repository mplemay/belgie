from belgie_core.core.belgie import Belgie
from belgie_oauth_server import OAuthServer
from fastapi import FastAPI
from fastapi.testclient import TestClient

AUTH_BASE_URL = "http://testserver/auth"


def test_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/auth/.well-known/oauth-authorization-server")
    assert response.status_code == 200

    payload = response.json()
    assert payload["issuer"] == AUTH_BASE_URL
    assert payload["authorization_endpoint"] == f"{AUTH_BASE_URL}/oauth2/authorize"
    assert payload["token_endpoint"] == f"{AUTH_BASE_URL}/oauth2/token"
    assert payload["registration_endpoint"] == f"{AUTH_BASE_URL}/oauth2/register"
    assert payload["revocation_endpoint"] == f"{AUTH_BASE_URL}/oauth2/revoke"
    assert payload["introspection_endpoint"] == f"{AUTH_BASE_URL}/oauth2/introspect"
    assert payload["grant_types_supported"] == ["authorization_code", "client_credentials", "refresh_token"]
    assert payload["response_modes_supported"] == ["query"]
    assert payload["token_endpoint_auth_methods_supported"] == [
        "client_secret_basic",
        "client_secret_post",
    ]
    assert payload["revocation_endpoint_auth_methods_supported"] == [
        "client_secret_basic",
        "client_secret_post",
    ]
    assert payload["introspection_endpoint_auth_methods_supported"] == [
        "client_secret_basic",
        "client_secret_post",
    ]


def test_metadata_alias_endpoint(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-authorization-server/auth")
    assert response.status_code == 200
    assert response.json()["issuer"] == AUTH_BASE_URL


def test_openid_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/auth/.well-known/openid-configuration")
    assert response.status_code == 200

    payload = response.json()
    assert payload["issuer"] == AUTH_BASE_URL
    assert payload["userinfo_endpoint"] == f"{AUTH_BASE_URL}/oauth2/userinfo"
    assert payload["end_session_endpoint"] == f"{AUTH_BASE_URL}/oauth2/end-session"
    assert payload["id_token_signing_alg_values_supported"] == ["RS256"]
    assert payload["response_modes_supported"] == ["query"]


def test_root_metadata_fallbacks_are_not_exposed(client: TestClient) -> None:
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404
    assert client.get("/.well-known/openid-configuration").status_code == 404


def test_protected_resource_metadata_routes_are_not_exposed(client: TestClient) -> None:
    assert client.get("/.well-known/oauth-protected-resource").status_code == 404
    assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 404


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
            "/auth/.well-known/oauth-authorization-server",
            "/.well-known/oauth-authorization-server/auth",
            "/auth/.well-known/openid-configuration",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert "authorization_endpoint" not in response.json()

        response = client.get("/auth/oauth2/authorize", follow_redirects=False)
        assert response.status_code == 404
