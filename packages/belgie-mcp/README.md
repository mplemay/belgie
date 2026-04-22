# belgie-mcp

> [!WARNING]
> This package follows the current MCP Python SDK auth APIs. Expect small
> compatibility updates as the SDK evolves.

`belgie-mcp` is the MCP bridge for Belgie OAuth. It builds MCP `AuthSettings`,
provides a `TokenVerifier`, and helps resource servers publish Better
Auth-style protected-resource metadata.

OAuth protocol behavior still lives in `belgie-oauth-server`. `belgie-mcp`
only adapts that behavior into MCP-facing types.

## Installation

```bash
uv add belgie[mcp] belgie[oauth]
```

## Quick Start

```python
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import MCPServer

from belgie import Belgie
from belgie.mcp import Mcp
from belgie.oauth.server import OAuthServer

app = FastAPI()

belgie = Belgie(
    settings=...,
    adapter=...,
    database=...,
)

oauth_settings = OAuthServer(
    adapter=...,
    base_url="https://auth.local",
    login_url="/login",
    consent_url="/consent",
    valid_audiences=["https://app.local/mcp"],
)

_ = belgie.add_plugin(oauth_settings)
mcp_plugin = belgie.add_plugin(
    Mcp(
        oauth=oauth_settings,
        base_url="https://app.local",
    ),
)

mcp_server = MCPServer(
    name="Belgie MCP",
    instructions="MCP server protected by Belgie OAuth",
    token_verifier=mcp_plugin.token_verifier,
    auth=mcp_plugin.auth,
)

app.include_router(belgie.router)
app.mount(
    mcp_plugin.server_path,
    mcp_server.streamable_http_app(streamable_http_path="/"),
)


@app.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata() -> JSONResponse:
    metadata = mcp_plugin.protected_resource_metadata(scopes_supported=["user"])
    return JSONResponse(metadata.model_dump(mode="json", exclude_none=True))


@mcp_server.tool()
async def get_time() -> dict[str, str]:
    return {"current_time": "2026-04-21T00:00:00+00:00"}
```

## Resource Metadata Flow

This package follows the same protected-resource split that Better Auth
documents:

- the auth server publishes OAuth and OIDC discovery metadata
- the MCP server publishes `/.well-known/oauth-protected-resource`

Use `McpPlugin.protected_resource_metadata(...)` to build that document from the
same OAuth settings that power the verifier.

## Configuration Notes

- `server_url` takes precedence over `base_url` plus `server_path`.
- If `server_url` is omitted, `Mcp` derives it from `base_url` and
  `server_path`.
- `oauth_strict=True` enables strict audience checks during verification.
- `required_scopes` applies MCP-side scope checks after token verification.
- `mcp_token_verifier(...)` defaults remote introspection to the OAuth server's
  advertised Better Auth-compatible path: `{issuer}/oauth2/introspect`.
- If you need remote introspection, set `introspection_endpoint`,
  `introspection_client_id`, and `introspection_client_secret`.
- `resource_metadata_mappings` maps non-URL audience strings (e.g. URNs) to a full protected-resource metadata URL,
  matching
  [better-auth `handleMcpErrors`](https://github.com/better-auth/better-auth/blob/main/packages/oauth-provider/src/mcp.ts).
  Use with `McpPlugin.mcp_www_authenticate_value(...)` or `build_mcp_www_authenticate_value(...)` when you return 401
  responses outside `MCPServer.streamable_http_app` (the SDK still sets `www-authenticate` for you).

## Public Surface

The primary public surface is:

- `Mcp`
- `McpPlugin`
- `BelgieOAuthTokenVerifier`
- `mcp_auth`
- `mcp_token_verifier`
- `build_mcp_www_authenticate_value`

The older top-level `get_user_from_access_token` helper is no longer part of
the recommended public API. If you need application-specific subject-to-user
resolution, build that lookup from the verified token payload in your own app.

## Compatibility Notes

- The removed `prefix="/oauth"` and `OAuthServerResource` setup does not come
  back here.
- Protected-resource metadata is resource-server-owned. `belgie-mcp` does not
  add auth-server-owned fallback metadata routes.
- The bundled verifier follows the OAuth server metadata contract, so its
  default introspection URL matches `belgie-oauth-server` discovery output.
