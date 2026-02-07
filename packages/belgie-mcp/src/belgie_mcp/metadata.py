from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.shared.auth import ProtectedResourceMetadata

_ROOT_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"


if TYPE_CHECKING:
    from fastapi.responses import Response
    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl


def create_protected_resource_metadata_router(
    auth: AuthSettings,
    *,
    include_root_fallback: bool = True,
    authorization_server_url: str | AnyHttpUrl | None = None,
) -> APIRouter:
    if auth.resource_server_url is None:
        msg = "AuthSettings.resource_server_url is required to build protected resource metadata"
        raise ValueError(msg)

    issuer_url = str(auth.issuer_url) if authorization_server_url is None else str(authorization_server_url)
    metadata = ProtectedResourceMetadata(
        resource=auth.resource_server_url,
        authorization_servers=[issuer_url],
        scopes_supported=auth.required_scopes,
    )

    metadata_url = build_resource_metadata_url(auth.resource_server_url)
    parsed = urlparse(str(metadata_url))
    well_known_path = parsed.path

    router = APIRouter()

    async def metadata_handler(_: Request) -> Response:
        return PydanticJSONResponse(
            content=metadata,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    router.add_api_route(well_known_path, metadata_handler, methods=["GET"])

    if include_root_fallback and well_known_path != _ROOT_RESOURCE_METADATA_PATH:
        router.add_api_route(_ROOT_RESOURCE_METADATA_PATH, metadata_handler, methods=["GET"])

    return router
