from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from belgie_core.core.plugin import PluginClient
from belgie_organization.plugin import OrganizationPlugin
from fastapi import APIRouter, Depends, Request
from fastapi.security import SecurityScopes

from belgie_team.client import TeamClient

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings

    from belgie_team.settings import Team


class TeamPlugin(PluginClient):
    def __init__(self, _belgie_settings: BelgieSettings, settings: Team) -> None:
        self._settings = settings
        self._resolve_client: Callable[..., Awaitable[TeamClient]] | None = None

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        async def resolve_client(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> TeamClient:
            user = await client.get_user(SecurityScopes(), request)
            session = await client.get_session(request)
            return TeamClient(
                client=client,
                settings=self._settings,
                adapter=self._settings.adapter,
                current_user=user,
                current_session=session,
            )

        resolve_client.__annotations__["request"] = Request
        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    async def __call__(self, *args: object, **kwargs: object) -> TeamClient:
        if self._resolve_client is None:
            msg = "TeamPlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    def router(self, belgie: Belgie) -> APIRouter:
        if not any(isinstance(plugin, OrganizationPlugin) for plugin in belgie.plugins):
            msg = "team plugin requires organization plugin to be registered"
            raise RuntimeError(msg)

        self._ensure_dependency_resolver(belgie)
        return APIRouter(prefix=self._settings.prefix, tags=["team"])

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None
