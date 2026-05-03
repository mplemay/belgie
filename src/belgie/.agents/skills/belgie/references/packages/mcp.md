# MCP

Use this reference for MCP servers protected by Belgie OAuth and for OAuth protected-resource metadata.

## Package

- Umbrella install: `uv add "belgie[mcp,oauth]"`
- Direct package install: `uv add belgie-mcp belgie-oauth-server`
- Umbrella import: `from belgie.mcp import Mcp`
- OAuth server import: `from belgie.oauth.server import OAuthServer`

## Setup Pattern

Use the MCP Python SDK's auth integration. Do not invent a separate ASGI handler for token verification.

```python
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import MCPServer

from belgie.mcp import Mcp
from belgie.oauth.server import OAuthServer

oauth_settings = OAuthServer(
    adapter=oauth_adapter,
    base_url="https://auth.example.com",
    login_url="/login",
    consent_url="/consent",
    valid_audiences=["https://api.example.com/mcp"],
)

belgie.add_plugin(oauth_settings)
mcp_plugin = belgie.add_plugin(Mcp(oauth=oauth_settings, base_url="https://api.example.com"))

mcp_server = MCPServer(
    name="Belgie MCP",
    instructions="MCP server protected by Belgie OAuth",
    token_verifier=mcp_plugin.token_verifier,
    auth=mcp_plugin.auth,
)

app.mount(
    mcp_plugin.server_path,
    mcp_server.streamable_http_app(streamable_http_path="/"),
)


@app.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata() -> JSONResponse:
    metadata = mcp_plugin.protected_resource_metadata(scopes_supported=["user"])
    return JSONResponse(metadata.model_dump(mode="json", exclude_none=True))
```

## Configuration Notes

- `server_url` overrides `base_url` plus `server_path`.
- `oauth_strict=True` enables strict audience checks.
- `required_scopes` applies MCP-side scope checks after token verification.
- Remote introspection defaults to `{issuer}/oauth2/introspect`.
- Set `introspection_endpoint`, `introspection_client_id`, and `introspection_client_secret` for remote introspection.
- Use `resource_metadata_mappings` for non-URL audiences that need metadata URLs.
