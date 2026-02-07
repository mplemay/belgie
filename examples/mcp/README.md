# Belgie MCP + OAuth Example

This example hosts the Belgie OAuth authorization server and an MCP resource server on a **single FastAPI app**.
The MCP server validates bearer tokens by introspecting against the co-located OAuth server.

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
- `POST /mcp` (MCP streamable HTTP endpoint)
- `GET /.well-known/oauth-protected-resource/mcp`
- `GET /.well-known/oauth-protected-resource`

## Notes

- The MCP server is mounted at `/mcp` and configured via `McpPlugin`.
- OAuth discovery serving (`/.well-known/oauth-authorization-server*` and
  `/.well-known/oauth-protected-resource*`) is owned by `OAuthPlugin`.
- Set `OAuthSettings.resource_server_url` to the MCP URL so protected resource
  metadata is published at the RFC9728 well-known endpoint.
- The example uses SQLite and will create `./belgie_mcp_example.db` in the working directory.
