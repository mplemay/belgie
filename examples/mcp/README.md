# Belgie MCP + OAuth Example

This example hosts the Belgie OAuth authorization server and an MCP resource server on a **single FastAPI app**.
The MCP server validates bearer tokens against the co-located OAuth provider state when available, and falls back to
HTTP introspection for external OAuth deployments.

## Setup

1. Install dependencies from the project root:

```bash
uv add belgie[mcp] belgie[oauth] belgie[alchemy] fastapi uvicorn sqlalchemy aiosqlite
```

2. Run the server:

```bash
uvicorn examples.mcp.main:app --reload
```

The app runs at `http://localhost:8000`.

## Endpoints

- `GET /login`
- `GET /auth/oauth/.well-known/oauth-authorization-server`
- `GET /.well-known/oauth-authorization-server/auth/oauth`
- `GET|POST /auth/oauth/authorize`
- `POST /auth/oauth/token`
- `POST /auth/oauth/introspect`
- `POST /mcp/` (MCP streamable HTTP endpoint)
- `GET /.well-known/oauth-protected-resource/mcp`
- `GET /.well-known/oauth-protected-resource`

## Notes

- The example mounts the MCP SDK's `streamable_http_app(...)` directly with `app.mount(mcp_plugin.server_path, ...)`.
- `McpPlugin` now only provides `auth`, `token_verifier`, and the derived `server_path`/`server_url`; mounting and
  streamable HTTP transport configuration are owned by the application.
- If you need transport security settings such as allowed hosts/origins, pass them directly to
  `mcp_server.streamable_http_app(...)`.
- OAuth discovery serving (`/.well-known/oauth-authorization-server*` and
  `/.well-known/oauth-protected-resource*`) is owned by `OAuthServerPlugin`.
- Configure `OAuthServer.resources=[OAuthResource(prefix="/mcp", ...)]` so protected
  resource metadata is published at the RFC9728 well-known endpoint.
- `SimpleOAuthProvider` keeps clients and tokens in memory, so deploys and restarts invalidate previously issued
  tokens.
- The example uses SQLite and will create `./belgie_mcp_example.db` in the working directory.
