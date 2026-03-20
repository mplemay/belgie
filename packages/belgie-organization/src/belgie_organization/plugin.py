from __future__ import annotations

import inspect
from importlib import import_module
from typing import TYPE_CHECKING

from belgie_core.core.plugin import PluginClient
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from fastapi import APIRouter, Depends, Request
from fastapi.security import SecurityScopes

from belgie_organization.client import OrganizationClient

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings
    from belgie_team.plugin import TeamPlugin

    from belgie_organization.settings import Organization


class OrganizationPlugin[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](PluginClient):
    def __init__(
        self,
        _belgie_settings: BelgieSettings,
        settings: Organization[OrganizationT, MemberT, InvitationT],
    ) -> None:
        self._settings = settings
        self._resolve_client: (
            Callable[..., Awaitable[OrganizationClient[OrganizationT, MemberT, InvitationT]]] | None
        ) = None

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        team_plugin: TeamPlugin | None = None
        try:
            team_plugin_type = import_module("belgie_team.plugin").TeamPlugin
        except ModuleNotFoundError:
            team_plugin_type = None

        if team_plugin_type is not None:
            team_plugin = next(
                (plugin for plugin in belgie.plugins if isinstance(plugin, team_plugin_type)),
                None,
            )

        async def resolve_client(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> OrganizationClient[OrganizationT, MemberT, InvitationT]:
            user = await client.get_user(SecurityScopes(), request)
            return OrganizationClient(
                client=client,
                settings=self._settings,
                current_user=user,
                maximum_members_per_team=None if team_plugin is None else team_plugin.settings.maximum_members_per_team,
            )

        resolve_client.__annotations__["request"] = Request
        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    @property
    def settings(self) -> Organization[OrganizationT, MemberT, InvitationT]:
        return self._settings

    async def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> OrganizationClient[OrganizationT, MemberT, InvitationT]:
        if self._resolve_client is None:
            msg = (
                "OrganizationPlugin dependency requires router initialization "
                "(call app.include_router(belgie.router) first)"
            )
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    def router(self, belgie: Belgie) -> APIRouter:
        self._ensure_dependency_resolver(belgie)
        return APIRouter(tags=["organization"])

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None
