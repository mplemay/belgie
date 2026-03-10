from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from belgie_core.core.plugin import PluginClient
from belgie_oauth_server.plugin import OAuthServerPlugin
from fastapi import APIRouter
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from belgie_mcp.verifier import mcp_auth, mcp_token_verifier

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_oauth_server.provider import SimpleOAuthProvider
    from belgie_oauth_server.settings import OAuthServer
    from fastapi import FastAPI
    from mcp.server.auth.provider import TokenVerifier
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.mcpserver import MCPServer
    from mcp.server.streamable_http import EventStore
    from pydantic import AnyHttpUrl
    from starlette.applications import Starlette
    from starlette.types import ASGIApp, Receive, Scope, Send

_STREAMABLE_HTTP_METHODS = ["DELETE", "GET", "POST"]


@dataclass(slots=True, kw_only=True, frozen=True)
class Mcp:
    oauth: OAuthServer
    server_url: str | AnyHttpUrl | None = None
    base_url: str | AnyHttpUrl | None = None
    server_path: str = "/mcp"
    required_scopes: list[str] | None = None
    introspection_endpoint: str | None = None
    oauth_strict: bool = False

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

    def mount_streamable_http(  # noqa: PLR0913
        self,
        app: FastAPI | Starlette,
        server: MCPServer,
        *,
        host: str = "127.0.0.1",
        json_response: bool = False,
        stateless_http: bool = False,
        event_store: EventStore | None = None,
        retry_interval: int | None = None,
        transport_security: TransportSecuritySettings | None = None,
    ) -> Starlette:
        if transport_security is None:
            transport_security = _build_transport_security(self.server_url)

        mcp_app = server.streamable_http_app(
            streamable_http_path="/",
            json_response=json_response,
            stateless_http=stateless_http,
            event_store=event_store,
            retry_interval=retry_interval,
            transport_security=transport_security,
            host=host,
        )
        if self.server_path != "/":
            app.router.routes.append(
                Route(
                    self.server_path,
                    endpoint=_McpPathAlias(app=mcp_app, mount_path=self.server_path),
                    methods=_STREAMABLE_HTTP_METHODS,
                    include_in_schema=False,
                ),
            )
        app.mount(self.server_path, mcp_app)
        return mcp_app

    def _resolve_oauth_provider(self) -> SimpleOAuthProvider | None:
        return None if self._oauth_plugin is None else self._oauth_plugin.provider


@dataclass(slots=True, kw_only=True, frozen=True)
class _McpPathAlias:
    app: ASGIApp
    mount_path: str

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Rewrite /mcp to the mounted child shape so the request still runs through MCP auth middleware.
        scope["path"] = "/"
        scope["root_path"] = _join_root_path(str(scope.get("root_path", "")), self.mount_path)
        await self.app(scope, receive, send)


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


def _extract_server_path(server_url: str) -> str:
    path = urlparse(server_url).path.rstrip("/")
    return path or "/"


def _join_root_path(root_path: str, mount_path: str) -> str:
    normalized_root_path = root_path.rstrip("/")
    normalized_mount_path = mount_path.rstrip("/")
    if not normalized_mount_path:
        return normalized_root_path or "/"
    if not normalized_root_path:
        return normalized_mount_path
    return f"{normalized_root_path}{normalized_mount_path}"


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


def _build_transport_security(server_url: str) -> TransportSecuritySettings:
    if (parsed := urlparse(server_url)).scheme not in {"http", "https"} or parsed.hostname is None:
        msg = "server_url must be an absolute HTTP(S) URL to configure MCP transport security"
        raise ValueError(msg)

    resolved_port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    hostnames = _resolve_allowed_hostnames(parsed.hostname)
    allowed_hosts = sorted(
        {
            candidate
            for hostname in hostnames
            for candidate in (
                _format_host(hostname),
                f"{_format_host(hostname)}:{resolved_port}",
            )
        },
    )
    allowed_origins = sorted(
        {
            candidate
            for hostname in hostnames
            for candidate in (
                f"{parsed.scheme}://{_format_host(hostname)}",
                f"{parsed.scheme}://{_format_host(hostname)}:{resolved_port}",
            )
        },
    )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _resolve_allowed_hostnames(hostname: str) -> set[str]:
    if _is_loopback_hostname(hostname):
        return {"localhost", "127.0.0.1", "::1"}
    return {hostname}


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname == "localhost":
        return True

    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _format_host(hostname: str) -> str:
    return f"[{hostname}]" if ":" in hostname else hostname
