from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from belgie_core.core.plugin import PluginClient
from belgie_organization.plugin import OrganizationPlugin
from belgie_proto.organization import OrganizationTeamAdapterProtocol
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol
from fastapi import APIRouter, Depends, Request
from fastapi.security import SecurityScopes

from belgie_team.client import TeamClient

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings

    from belgie_team.settings import Team


class TeamPlugin[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT: TeamProtocol,
    TeamMemberT: TeamMemberProtocol,
](PluginClient):
    def __init__(
        self,
        _belgie_settings: BelgieSettings,
        settings: Team[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT],
    ) -> None:
        self._settings = settings
        self._resolve_client: (
            Callable[
                ...,
                Awaitable[TeamClient[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT]],
            ]
            | None
        ) = None

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        async def resolve_client(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> TeamClient[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT]:
            user = await client.get_user(SecurityScopes(), request)
            return TeamClient(
                client=client,
                settings=self._settings,
                current_user=user,
            )

        resolve_client.__annotations__["request"] = Request
        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    @property
    def settings(self) -> Team[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT]:
        return self._settings

    async def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> TeamClient[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT]:
        if self._resolve_client is None:
            msg = "TeamPlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    def router(self, belgie: Belgie) -> APIRouter:
        organization_plugin = next(
            (plugin for plugin in belgie.plugins if isinstance(plugin, OrganizationPlugin)),
            None,
        )
        if organization_plugin is None:
            msg = "team plugin requires organization plugin to be registered"
            raise RuntimeError(msg)
        if not isinstance(organization_plugin.settings.adapter, OrganizationTeamAdapterProtocol):
            msg = "team plugin requires organization plugin to use a team-capable adapter"
            raise TypeError(msg)

        self._ensure_dependency_resolver(belgie)
        return APIRouter(tags=["team"])

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None
