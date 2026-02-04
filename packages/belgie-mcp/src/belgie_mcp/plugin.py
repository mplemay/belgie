from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from belgie_mcp.metadata import create_protected_resource_metadata_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from mcp.server.mcpserver import MCPServer


class BelgieMcpPlugin:
    def __init__(  # noqa: PLR0913
        self,
        server: MCPServer,
        *,
        mount_path: str = "/mcp",
        streamable_http_path: str = "/",
        host: str = "localhost",
        include_protected_resource_metadata: bool = True,
        include_root_fallback: bool = True,
        manage_lifespan: bool = True,
    ) -> None:
        if not mount_path:
            msg = "mount_path must be provided"
            raise ValueError(msg)

        if not streamable_http_path:
            msg = "streamable_http_path must be provided"
            raise ValueError(msg)

        self.server = server
        self.mount_path = mount_path
        self.streamable_http_path = streamable_http_path
        self.host = host
        self.include_protected_resource_metadata = include_protected_resource_metadata
        self.include_root_fallback = include_root_fallback
        self.manage_lifespan = manage_lifespan

    def install(self, app: FastAPI) -> None:
        mcp_app = self.server.streamable_http_app(
            streamable_http_path=self.streamable_http_path,
            host=self.host,
        )
        app.mount(self.mount_path, mcp_app)

        if self.include_protected_resource_metadata and self.server.settings.auth:
            app.include_router(
                create_protected_resource_metadata_router(
                    self.server.settings.auth,
                    include_root_fallback=self.include_root_fallback,
                ),
            )

        if self.manage_lifespan:
            self._wrap_lifespan(app)

    def _wrap_lifespan(self, app: FastAPI) -> None:
        if getattr(app.state, "belgie_mcp_lifespan_wrapped", False):
            return

        existing_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def _lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
            async with self.server.session_manager.run(), existing_lifespan(app_instance):
                yield

        app.router.lifespan_context = _lifespan
        app.state.belgie_mcp_lifespan_wrapped = True
