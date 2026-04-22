from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from belgie_core.core.plugin import PluginClient
from belgie_oauth_server import build_protected_resource_metadata
from belgie_oauth_server.plugin import OAuthServerPlugin
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from belgie_mcp.verifier import mcp_auth, mcp_token_verifier
from belgie_mcp.www_authenticate import build_mcp_www_authenticate_value

if TYPE_CHECKING:
    from collections.abc import Sequence

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_oauth_server.models import ProtectedResourceMetadata
    from belgie_oauth_server.provider import SimpleOAuthProvider
    from belgie_oauth_server.settings import OAuthServer
    from mcp.server.auth.provider import TokenVerifier
    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl


@dataclass(slots=True, kw_only=True, frozen=True)
class Mcp:
    oauth: OAuthServer
    server_url: str | AnyHttpUrl | None = None
    base_url: str | AnyHttpUrl | None = None
    server_path: str = "/mcp"
    required_scopes: list[str] | None = None
    introspection_endpoint: str | None = None
    introspection_client_id: str | None = None
    introspection_client_secret: str | None = None
    oauth_strict: bool = False
    resource_metadata_mappings: dict[str, str] | None = None

    def __call__(self, belgie_settings: BelgieSettings) -> McpPlugin:
        return McpPlugin(belgie_settings, self)


class McpPlugin(PluginClient):
    def __init__(self, belgie_settings: BelgieSettings, settings: Mcp) -> None:
        resolved_base_url = settings.base_url if settings.base_url is not None else belgie_settings.base_url
        resolved_server_url = (
            str(settings.server_url)
            if settings.server_url is not None
            else _build_server_url(_require_base_url(resolved_base_url), settings.server_path)
        )
        self._oauth_settings = settings.oauth
        self._mcp_config = settings
        self._oauth_plugin: OAuthServerPlugin | None = None
        self.auth = mcp_auth(
            settings.oauth,
            server_url=resolved_server_url,
            required_scopes=settings.required_scopes,
        )
        self.token_verifier = mcp_token_verifier(
            settings.oauth,
            server_url=resolved_server_url,
            introspection_endpoint=settings.introspection_endpoint,
            introspection_client_id=settings.introspection_client_id,
            introspection_client_secret=settings.introspection_client_secret,
            oauth_strict=settings.oauth_strict,
            provider_resolver=self._resolve_oauth_provider,
        )
        self.server_url = resolved_server_url
        self.server_path = _extract_server_path(resolved_server_url)

    auth: AuthSettings
    token_verifier: TokenVerifier
    server_url: str
    server_path: str

    def router(self, belgie: Belgie) -> APIRouter:
        if self._oauth_plugin is None:
            self._oauth_plugin = _resolve_oauth_plugin(belgie.plugins, self._oauth_settings)
        return APIRouter()

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None

    def protected_resource_router(self) -> APIRouter:
        """Serves `/.well-known/oauth-protected-resource/...` for this MCP resource.

        Use when the MCP app is not using ``MCPServer.streamable_http_app`` built-in well-known
        registration; ``include_router(plugin.protected_resource_router())`` on the FastAPI app.
        """
        metadata = self.protected_resource_metadata()
        parsed = urlparse(self.server_url)
        path = parsed.path.rstrip("/")
        if path in ("", "/"):
            route = "/.well-known/oauth-protected-resource"
        else:
            route = f"/.well-known/oauth-protected-resource{path}"
        body = metadata.model_dump(mode="json", exclude_none=True)
        cache = "public, max-age=15, stale-while-revalidate=15, stale-if-error=86400"
        router = APIRouter()

        @router.get(
            route,
            tags=["mcp", "well-known"],
            name="mcp_oauth_protected_resource_metadata",
        )
        def protected_resource_get() -> JSONResponse:
            return JSONResponse(
                content=body,
                headers={"Cache-Control": cache, "Content-Type": "application/json"},
            )

        return router

    def _resolve_oauth_provider(self) -> SimpleOAuthProvider | None:
        return None if self._oauth_plugin is None else self._oauth_plugin.provider

    @property
    def resource_metadata_mappings(self) -> dict[str, str] | None:
        return self._mcp_config.resource_metadata_mappings

    def mcp_www_authenticate_value(self, resources: str | list[str]) -> str:
        """``WWW-Authenticate`` for 401s when handling MCP HTTP outside the SDK's built-in responses."""
        return build_mcp_www_authenticate_value(
            resources,
            resource_metadata_mappings=self._mcp_config.resource_metadata_mappings,
        )

    def protected_resource_metadata(
        self,
        *,
        scopes_supported: Sequence[str] | None = None,
        external_scopes: Sequence[str] | None = None,
        silence_oidc_scope_warnings: bool = False,
    ) -> ProtectedResourceMetadata:
        return build_protected_resource_metadata(
            self.server_url,
            authorization_server=str(self.auth.issuer_url),
            settings=self._oauth_settings,
            scopes_supported=scopes_supported,
            external_scopes=external_scopes,
            silence_oidc_scope_warnings=silence_oidc_scope_warnings,
        )


def _require_base_url(base_url: str | AnyHttpUrl | None) -> str:
    if base_url is None:
        msg = "base_url is required when server_url is not provided"
        raise ValueError(msg)
    return str(base_url)


def _build_server_url(base_url: str, server_path: str) -> str:
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    full_path = f"{base_path}{server_path}" if base_path else server_path
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))


def _extract_server_path(server_url: str) -> str:
    return urlparse(server_url).path or "/"


def _resolve_oauth_plugin(
    plugins: list[PluginClient],
    settings: OAuthServer,
) -> OAuthServerPlugin | None:
    if matched_plugins := [
        plugin for plugin in plugins if isinstance(plugin, OAuthServerPlugin) and plugin.settings is settings
    ]:
        return matched_plugins[0]

    oauth_plugins = [plugin for plugin in plugins if isinstance(plugin, OAuthServerPlugin)]
    return oauth_plugins[0] if len(oauth_plugins) == 1 else None
