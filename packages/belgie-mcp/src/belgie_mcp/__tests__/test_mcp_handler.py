from belgie_mcp.mcp_handler import mcp_handler
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def _ok(_request):
    return PlainTextResponse("ok")


def test_mcp_handler_returns_401_with_www_authenticate_when_token_missing() -> None:
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint="https://issuer.local/auth/oauth2/introspect",
        server_url="https://mcp.local/mcp",
    )
    inner = Starlette(routes=[Route("/", _ok)])

    app = mcp_handler(verifier, inner)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 401
    assert r.json() == {"error": "invalid_token"}
    www = r.headers.get("www-authenticate", "")
    assert "resource_metadata=" in www
    assert "https://mcp.local" in www


def test_mcp_handler_returns_401_when_bearer_invalid_without_provider() -> None:
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint="https://issuer.local/auth/oauth2/introspect",
        server_url="https://mcp.local/mcp",
    )
    inner = Starlette(routes=[Route("/", _ok)])
    app = mcp_handler(verifier, inner)
    client = TestClient(app)
    r = client.get("/", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401
    assert r.json() == {"error": "invalid_token"}
    www = r.headers.get("www-authenticate", "")
    assert "resource_metadata=" in www
    assert "https://mcp.local" in www
