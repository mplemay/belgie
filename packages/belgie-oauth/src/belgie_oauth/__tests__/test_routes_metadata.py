from fastapi.testclient import TestClient

AUTH_BASE_URL = "http://testserver/auth/oauth"


def test_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/auth/oauth/.well-known/oauth-authorization-server")
    assert response.status_code == 200

    payload = response.json()
    assert payload["issuer"] == AUTH_BASE_URL
    assert payload["authorization_endpoint"] == f"{AUTH_BASE_URL}/authorize"
    assert payload["token_endpoint"] == f"{AUTH_BASE_URL}/token"
    assert payload["introspection_endpoint"] == f"{AUTH_BASE_URL}/introspect"
