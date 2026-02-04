from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from belgie_core.core.protocols import Plugin
from fastapi import APIRouter

from belgie_mcp.metadata import create_protected_resource_metadata_router
from belgie_mcp.verifier import mcp_auth, mcp_token_verifier

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_oauth.settings import OAuthSettings
    from mcp.server.auth.provider import TokenVerifier
    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl


class McpPlugin(Plugin):
    def __init__(  # noqa: PLR0913
        self,
        settings: OAuthSettings,
        *,
        server_url: str | AnyHttpUrl | None = None,
        base_url: str | AnyHttpUrl | None = None,
        server_path: str = "/mcp",
        required_scopes: list[str] | None = None,
        introspection_endpoint: str | None = None,
        oauth_strict: bool = False,
        include_root_fallback: bool = True,
    ) -> None:
        resolved_server_url = (
            str(server_url) if server_url is not None else _build_server_url(_require_base_url(base_url), server_path)
        )
        self.auth = mcp_auth(
            settings,
            server_url=resolved_server_url,
            required_scopes=required_scopes,
        )
        self.token_verifier = mcp_token_verifier(
            settings,
            server_url=resolved_server_url,
            introspection_endpoint=introspection_endpoint,
            oauth_strict=oauth_strict,
        )
        self._include_root_fallback = include_root_fallback

    auth: AuthSettings
    token_verifier: TokenVerifier

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return APIRouter()

    def public_router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return create_protected_resource_metadata_router(
            self.auth,
            include_root_fallback=self._include_root_fallback,
        )


def _require_base_url(base_url: str | AnyHttpUrl | None) -> str:
    if base_url is None:
        msg = "base_url is required when server_url is not provided"
        raise ValueError(msg)
    return str(base_url)


def _build_server_url(base_url: str, server_path: str) -> str:
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    path_suffix = server_path.strip("/")
    full_path = (f"{base_path}/{path_suffix}" if base_path else f"/{path_suffix}") if path_suffix else base_path
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))
