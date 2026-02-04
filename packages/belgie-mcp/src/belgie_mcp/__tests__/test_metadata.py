import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from belgie_mcp.metadata import create_protected_resource_metadata_router
from mcp.server.auth.settings import AuthSettings


def test_protected_resource_metadata_routes() -> None:
    auth = AuthSettings(
        issuer_url="https://auth.local/oauth",
        resource_server_url="https://mcp.local/mcp",
        required_scopes=["user"],
    )

    app = FastAPI()
    app.include_router(create_protected_resource_metadata_router(auth, include_root_fallback=True))

    with TestClient(app) as client:
        path_response = client.get("/.well-known/oauth-protected-resource/mcp")
        assert path_response.status_code == 200

        payload = path_response.json()
        assert payload["resource"] == "https://mcp.local/mcp"
        assert payload["authorization_servers"] == ["https://auth.local/oauth"]
        assert payload["scopes_supported"] == ["user"]

        root_response = client.get("/.well-known/oauth-protected-resource")
        assert root_response.status_code == 200
        assert root_response.json() == payload
