# belgie-mcp

> [!WARNING]
> This package follows the current MCP Python SDK auth APIs. Expect small compatibility updates as the SDK evolves.

`belgie-mcp` connects Belgie's OAuth server to the MCP Python SDK. It builds MCP `AuthSettings`, provides a token
verifier that understands both local OAuth provider state and HTTP introspection, and includes a helper for resolving
the current user from the active access token.

## Installation

```bash
uv add belgie[mcp] belgie[oauth]
```

> [!NOTE]
> The `belgie.mcp` re-exports are only available when the `mcp` extra is installed. The quick-start also imports
> `belgie.oauth.server`, which requires the `oauth` extra.

## Quick Start

Here is a complete setup for a single FastAPI app that hosts both Belgie OAuth and an MCP server:

**Project Structure:**

```text
my-app/
├── main.py
└── ...
```

**main.py:**

```python
from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

from belgie import Belgie
from belgie.alchemy.oauth_server import OAuthServerAdapter
from belgie.mcp import Mcp, get_user_from_access_token
from belgie.oauth.server import OAuthServerResource, OAuthServer

app = FastAPI()

belgie = Belgie(
    settings=...,  # your BelgieSettings
    adapter=...,  # your database adapter
    database=...,  # async DB dependency
)

oauth_adapter = OAuthServerAdapter(
    oauth_client=...,  # your OAuth client model
    oauth_authorization_state=...,  # your OAuth authorization state model
    oauth_authorization_code=...,  # your OAuth authorization code model
    oauth_access_token=...,  # your OAuth access token model
    oauth_refresh_token=...,  # your OAuth refresh token model
    oauth_consent=...,  # your OAuth consent model
)

oauth_settings = OAuthServer(
    adapter=oauth_adapter,
    base_url="https://auth.local",
    prefix="/oauth",
    client_id="demo-client",
    client_secret="demo-secret",  # noqa: S106
    redirect_uris=["http://localhost:3030/callback"],
    default_scopes=["user"],
    login_url="/login",
    resources=[OAuthServerResource(prefix="/mcp", scopes=["user"])],
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
    mcp_server.streamable_http_app(
        streamable_http_path="/",
    ),
)


@mcp_server.tool()
async def get_user_email() -> dict[str, str | None]:
    user = await get_user_from_access_token(belgie)
    return {
        "individual_id": str(user.id) if user else None,
        "user_email": user.email if user else None,
    }
```

`McpPlugin` gives you the MCP auth settings, token verifier, and derived `server_path`. Your app owns the transport
mounting and any `streamable_http_app(...)` options.

## Notes

- `OAuthServer.adapter` is required because the MCP token verifier expects OAuth server state to be persistent.
- If the MCP server shares a host with Belgie, set `base_url` and let `Mcp` derive the resource URL from
  `server_path`.
- If you pass a `server_url` directly, it takes precedence over `base_url` and `server_path`.
- `oauth_strict=True` enables strict resource validation against the issued token audience.
- `get_user_from_access_token` resolves the current user from a co-located OAuth provider first, then falls back to
  decoding a JWT `sub` claim.
- The package is designed to work with the example in [`examples/mcp`](../../examples/mcp).
