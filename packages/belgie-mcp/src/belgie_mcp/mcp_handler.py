"""ASGI wrapper matching better-auth ``mcpHandler``: verify Bearer, attach ``WWW-Authenticate`` on failure."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from belgie_mcp.www_authenticate import build_mcp_www_authenticate_value

_OAUTH_BEARER_PARTS = 2


def _parse_bearer(headers: Mapping[str, str]) -> str | None:
    auth = headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != _OAUTH_BEARER_PARTS or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def mcp_handler(
    verifier: BelgieOAuthTokenVerifier,
    inner: ASGIApp,
    *,
    resource_metadata_mappings: dict[str, str] | None = None,
) -> ASGIApp:
    """Return an ASGI app that verifies a Bearer token before delegating to ``inner``.

    On verification failure, responds with 401, a minimal JSON error body, and ``WWW-Authenticate`` built
    from the verifier's configured resource URL, as in
    ``@better-auth/oauth-provider`` ``handleMcpErrors`` / ``mcp.ts``.
    """
    default_resource = verifier.resource_url

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        token = _parse_bearer(request.headers)
        if token is None:
            await _send_unauthorized(scope, receive, send, default_resource, resource_metadata_mappings)
            return

        if await verifier.verify_token(token) is None:
            await _send_unauthorized(scope, receive, send, default_resource, resource_metadata_mappings)
            return

        await inner(scope, receive, send)

    return app


async def _send_unauthorized(
    scope: Scope,
    receive: Receive,
    send: Send,
    resource: str,
    resource_metadata_mappings: dict[str, str] | None,
) -> None:
    www = build_mcp_www_authenticate_value(
        resource,
        resource_metadata_mappings=resource_metadata_mappings,
    )
    response = JSONResponse(
        status_code=401,
        content={"error": "invalid_token"},
        headers={"WWW-Authenticate": www},
    )
    await response(scope, receive, send)
