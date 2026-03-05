from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003

from belgie_core.core.plugin import PluginClient
from belgie_organization.plugin import OrganizationPlugin
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import SecurityScopes

from belgie_team.client import TeamClient
from belgie_team.models import (
    AddTeamMemberBody,
    CreateTeamBody,
    RemoveTeamBody,
    RemoveTeamMemberBody,
    SetActiveTeamBody,
    TeamMemberView,
    TeamView,
    UpdateTeamBody,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.team import TeamAdapterProtocol

    from belgie_team.settings import Team


class TeamPlugin(PluginClient):
    def __init__(
        self,
        _belgie_settings: BelgieSettings,
        settings: Team,
        adapter: TeamAdapterProtocol,
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._resolve_client: Callable[..., Coroutine[object, object, TeamClient]] | None = None

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        async def resolve_client(client: BelgieClient = Depends(belgie)) -> TeamClient:  # noqa: B008
            return TeamClient(
                client=client,
                settings=self._settings,
                adapter=self._adapter,
            )

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    async def __call__(self, *args: object, **kwargs: object) -> TeamClient:
        if self._resolve_client is None:
            msg = "TeamPlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: C901, PLR0915
        if not any(isinstance(plugin, OrganizationPlugin) for plugin in belgie.plugins):
            msg = "team plugin requires organization plugin to be registered"
            raise RuntimeError(msg)

        self._ensure_dependency_resolver(belgie)
        router = APIRouter(prefix=self._settings.prefix, tags=["team"])

        @router.post("/create", response_model=TeamView)
        async def create_team(
            body: CreateTeamBody,
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> TeamView:
            user = await team.client.get_user(SecurityScopes(), request)
            current_session = await team.client.get_session(request)
            organization_id = body.organization_id or _get_active_organization_id(current_session)
            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization_id is required",
                )
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )
            if self._settings.maximum_teams_per_organization is not None:
                teams = await team.list_teams(organization_id=organization_id)
                if len(teams) >= self._settings.maximum_teams_per_organization:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="maximum teams reached for this organization",
                    )
            created = await team.create_team(
                organization_id=organization_id,
                name=body.name,
            )
            return TeamView.model_validate(created)

        @router.get("/list", response_model=list[TeamView])
        async def list_teams(
            request: Request,
            organization_id: UUID | None = Query(default=None),  # noqa: B008, FAST002
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> list[TeamView]:
            user = await team.client.get_user(SecurityScopes(), request)
            current_session = await team.client.get_session(request)
            resolved_org_id = organization_id or _get_active_organization_id(current_session)
            if resolved_org_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization_id is required",
                )
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=resolved_org_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )
            teams = await team.list_teams(organization_id=resolved_org_id)
            return [TeamView.model_validate(row) for row in teams]

        @router.post("/set-active", response_model=TeamView | None)
        async def set_active_team(
            body: SetActiveTeamBody,
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> TeamView | None:
            user = await team.client.get_user(SecurityScopes(), request)
            current_session = await team.client.get_session(request)
            if body.team_id is None:
                await team.set_active_team(
                    session_id=current_session.id,
                    team_id=None,
                )
                return None
            team_row = await team.adapter.get_team_by_id(team.client.db, body.team_id)
            if team_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="team not found",
                )
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=team_row.organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )
            team_member = await team.adapter.get_team_member(
                team.client.db,
                team_id=team_row.id,
                user_id=user.id,
            )
            if team_member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this team",
                )
            await team.set_active_team(
                session_id=current_session.id,
                team_id=team_row.id,
            )
            return TeamView.model_validate(team_row)

        @router.get("/active", response_model=TeamView | None)
        async def get_active_team(
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> TeamView | None:
            user = await team.client.get_user(SecurityScopes(), request)
            current_session = await team.client.get_session(request)
            active_team_id = _get_active_team_id(current_session)
            if active_team_id is None:
                return None
            active_team = await team.adapter.get_team_by_id(team.client.db, active_team_id)
            if active_team is None:
                return None
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=active_team.organization_id,
                user_id=user.id,
            )
            if member is None:
                return None
            team_member = await team.adapter.get_team_member(
                team.client.db,
                team_id=active_team.id,
                user_id=user.id,
            )
            if team_member is None:
                return None
            return TeamView.model_validate(active_team)

        @router.post("/update", response_model=TeamView)
        async def update_team(
            body: UpdateTeamBody,
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> TeamView:
            user = await team.client.get_user(SecurityScopes(), request)
            team_row = await team.adapter.get_team_by_id(team.client.db, body.team_id)
            if team_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="team not found",
                )
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=team_row.organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )
            updated = await team.adapter.update_team(
                team.client.db,
                team_id=body.team_id,
                name=body.name,
            )
            if updated is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="team not found",
                )
            return TeamView.model_validate(updated)

        @router.post("/remove")
        async def remove_team(
            body: RemoveTeamBody,
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> dict[str, bool]:
            user = await team.client.get_user(SecurityScopes(), request)
            team_row = await team.adapter.get_team_by_id(team.client.db, body.team_id)
            if team_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="team not found",
                )
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=team_row.organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )
            removed = await team.adapter.remove_team(
                team.client.db,
                team_id=body.team_id,
            )
            return {"success": removed}

        @router.get("/members", response_model=list[TeamMemberView])
        async def list_team_members(
            request: Request,
            team_id: UUID | None = Query(default=None),  # noqa: B008, FAST002
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> list[TeamMemberView]:
            user = await team.client.get_user(SecurityScopes(), request)
            current_session = await team.client.get_session(request)
            resolved_team_id = team_id or _get_active_team_id(current_session)
            if resolved_team_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="team_id is required",
                )
            team_member = await team.adapter.get_team_member(
                team.client.db,
                team_id=resolved_team_id,
                user_id=user.id,
            )
            if team_member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this team",
                )
            members = await team.adapter.list_team_members(
                team.client.db,
                team_id=resolved_team_id,
            )
            return [TeamMemberView.model_validate(row) for row in members]

        @router.get("/user-teams", response_model=list[TeamView])
        async def list_user_teams(
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> list[TeamView]:
            user = await team.client.get_user(SecurityScopes(), request)
            teams = await team.adapter.list_teams_for_user(
                team.client.db,
                user_id=user.id,
            )
            return [TeamView.model_validate(row) for row in teams]

        @router.post("/add-member", response_model=TeamMemberView)
        async def add_team_member(
            body: AddTeamMemberBody,
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> TeamMemberView:
            user = await team.client.get_user(SecurityScopes(), request)
            team_row = await team.adapter.get_team_by_id(team.client.db, body.team_id)
            if team_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="team not found",
                )
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=team_row.organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )
            user_member = await team.adapter.get_member(
                team.client.db,
                organization_id=team_row.organization_id,
                user_id=body.user_id,
            )
            if user_member is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="target user is not in the organization",
                )
            if self._settings.maximum_members_per_team is not None:
                existing_members = await team.adapter.list_team_members(
                    team.client.db,
                    team_id=body.team_id,
                )
                if len(existing_members) >= self._settings.maximum_members_per_team:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="team member limit reached",
                    )
            existing = await team.adapter.get_team_member(
                team.client.db,
                team_id=body.team_id,
                user_id=body.user_id,
            )
            if existing is not None:
                return TeamMemberView.model_validate(existing)
            created = await team.add_team_member(
                team_id=body.team_id,
                user_id=body.user_id,
            )
            return TeamMemberView.model_validate(created)

        @router.post("/remove-member")
        async def remove_team_member(
            body: RemoveTeamMemberBody,
            request: Request,
            team: TeamClient = Depends(self),  # noqa: B008, FAST002
        ) -> dict[str, bool]:
            user = await team.client.get_user(SecurityScopes(), request)
            team_row = await team.adapter.get_team_by_id(team.client.db, body.team_id)
            if team_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="team not found",
                )
            member = await team.adapter.get_member(
                team.client.db,
                organization_id=team_row.organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )
            removed = await team.remove_team_member(
                team_id=body.team_id,
                user_id=body.user_id,
            )
            return {"success": removed}

        return router

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None


def _get_active_organization_id(session_obj: object) -> UUID | None:
    if not hasattr(session_obj, "active_organization_id"):
        msg = (
            "session model is missing 'active_organization_id'. "
            "Use belgie_alchemy.organization.mixins.OrganizationSessionMixin on your session model."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=msg,
        )
    return session_obj.active_organization_id  # type: ignore[attr-defined]


def _get_active_team_id(session_obj: object) -> UUID | None:
    if not hasattr(session_obj, "active_team_id"):
        msg = (
            "session model is missing 'active_team_id'. "
            "Use belgie_alchemy.team.mixins.TeamSessionMixin on your session model."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=msg,
        )
    return session_obj.active_team_id  # type: ignore[attr-defined]
