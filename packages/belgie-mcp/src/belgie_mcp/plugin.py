from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from belgie_core.core.plugin import Plugin
from fastapi import APIRouter

from belgie_mcp.verifier import mcp_auth, mcp_token_verifier

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_oauth_server.settings import OAuthServerSettings
    from mcp.server.auth.provider import TokenVerifier
    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl


@dataclass(slots=True, kw_only=True, frozen=True)
class McpPluginSettings:
    oauth_settings: OAuthServerSettings
    server_url: str | AnyHttpUrl | None = None
    base_url: str | AnyHttpUrl | None = None
    server_path: str = "/mcp"
    required_scopes: list[str] | None = None
    introspection_endpoint: str | None = None
    oauth_strict: bool = False


class McpPlugin(Plugin[McpPluginSettings]):
    def __init__(self, belgie_settings: BelgieSettings, settings: McpPluginSettings) -> None:
        resolved_base_url = settings.base_url if settings.base_url is not None else belgie_settings.base_url
        resolved_server_url = (
            str(settings.server_url)
            if settings.server_url is not None
            else _build_server_url(_require_base_url(resolved_base_url), settings.server_path)
        )
        self.auth = mcp_auth(
            settings.oauth_settings,
            server_url=resolved_server_url,
            required_scopes=settings.required_scopes,
        )
        self.token_verifier = mcp_token_verifier(
            settings.oauth_settings,
            server_url=resolved_server_url,
            introspection_endpoint=settings.introspection_endpoint,
            oauth_strict=settings.oauth_strict,
        )

    auth: AuthSettings
    token_verifier: TokenVerifier

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return APIRouter()

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None


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
