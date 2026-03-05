from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID  # noqa: TC003

from belgie_core.core.plugin import PluginClient
from belgie_proto.organization import OrganizationAdapterProtocol
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import SecurityScopes

from belgie_organization.client import OrganizationClient
from belgie_organization.models import (
    AcceptInvitationBody,
    AcceptInvitationView,
    CreateOrganizationBody,
    GetFullOrganizationQuery,
    InvitationView,
    InviteMemberBody,
    MemberView,
    OrganizationFullView,
    OrganizationView,
    SetActiveOrganizationBody,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.member import MemberProtocol
    from belgie_proto.organization.organization import OrganizationProtocol
    from belgie_proto.organization.session import OrganizationSessionProtocol

    from belgie_organization.settings import Organization

    type OrganizationAdapterCast = OrganizationAdapterProtocol[
        OrganizationProtocol,
        MemberProtocol,
        InvitationProtocol,
        OrganizationSessionProtocol,
    ]


class OrganizationPlugin(PluginClient):
    def __init__(self, _belgie_settings: BelgieSettings, settings: Organization) -> None:
        self._settings = settings
        self._resolve_client: Callable[..., Coroutine[object, object, OrganizationClient]] | None = None

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        async def resolve_client(client: BelgieClient = Depends(belgie)) -> OrganizationClient:  # noqa: B008
            if not isinstance(client.adapter, OrganizationAdapterProtocol):
                msg = (
                    "organization plugin requires an adapter implementing "
                    "OrganizationAdapterProtocol. Use "
                    "belgie_alchemy.organization.OrganizationAdapter or "
                    "belgie_alchemy.team.TeamAdapter."
                )
                raise TypeError(msg)
            adapter = cast("OrganizationAdapterCast", client.adapter)
            return OrganizationClient(
                client=client,
                settings=self._settings,
                adapter=adapter,
            )

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    async def __call__(self, *args: object, **kwargs: object) -> OrganizationClient:
        if self._resolve_client is None:
            msg = (
                "OrganizationPlugin dependency requires router initialization "
                "(call app.include_router(belgie.router) first)"
            )
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: C901, PLR0915
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(prefix=self._settings.prefix, tags=["organization"])

        @router.post("/create", response_model=OrganizationFullView)
        async def create_organization(
            body: CreateOrganizationBody,
            request: Request,
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> OrganizationFullView:
            user = await organization.client.get_user(SecurityScopes(), request)
            if body.user_id is not None and body.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="cannot create organization for another user from client session",
                )
            if not self._settings.allow_user_to_create_organization:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="organization creation is disabled",
                )
            if await organization.adapter.get_organization_by_slug(organization.client.db, body.slug):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization slug already taken",
                )
            created_organization, created_member = await organization.create_organization(
                user_id=body.user_id or user.id,
                name=body.name,
                slug=body.slug,
                logo=body.logo,
                metadata=body.metadata,
            )
            if not body.keep_current_active_organization:
                current_session = await organization.client.get_session(request)
                await organization.set_active_organization(
                    session_id=current_session.id,
                    organization_id=created_organization.id,
                )
            return OrganizationFullView(
                organization=OrganizationView.model_validate(created_organization),
                members=[MemberView.model_validate(created_member)],
                invitations=[],
            )

        @router.get("/list", response_model=list[OrganizationView])
        async def list_organizations(
            request: Request,
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> list[OrganizationView]:
            user = await organization.client.get_user(SecurityScopes(), request)
            organizations = await organization.list_organizations_for_user(user.id)
            return [OrganizationView.model_validate(row) for row in organizations]

        @router.post("/set-active", response_model=OrganizationView | None)
        async def set_active_organization(
            body: SetActiveOrganizationBody,
            request: Request,
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> OrganizationView | None:
            user = await organization.client.get_user(SecurityScopes(), request)
            current_session = await organization.client.get_session(request)
            if body.organization_id is None and body.organization_slug is None:
                await organization.set_active_organization(
                    session_id=current_session.id,
                    organization_id=None,
                )
                return None

            organization_id = body.organization_id
            if organization_id is None and body.organization_slug is not None:
                by_slug = await organization.adapter.get_organization_by_slug(
                    organization.client.db,
                    body.organization_slug,
                )
                if by_slug is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="organization not found",
                    )
                organization_id = by_slug.id

            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization_id or organization_slug is required",
                )

            member = await organization.adapter.get_member(
                organization.client.db,
                organization_id=organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )

            await organization.set_active_organization(
                session_id=current_session.id,
                organization_id=organization_id,
            )
            active = await organization.adapter.get_organization_by_id(
                organization.client.db,
                organization_id,
            )
            if active is None:
                return None
            return OrganizationView.model_validate(active)

        @router.get("/active", response_model=OrganizationView | None)
        async def get_active_organization(
            request: Request,
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> OrganizationView | None:
            user = await organization.client.get_user(SecurityScopes(), request)
            current_session = await organization.client.get_session(request)
            active_organization_id = _get_active_organization_id(current_session)
            if active_organization_id is None:
                return None
            active = await organization.adapter.get_organization_by_id(
                organization.client.db,
                active_organization_id,
            )
            if active is None:
                return None
            member = await organization.adapter.get_member(
                organization.client.db,
                organization_id=active.id,
                user_id=user.id,
            )
            if member is None:
                return None
            return OrganizationView.model_validate(active)

        @router.get("/full", response_model=OrganizationFullView | None)
        async def get_full_organization(
            request: Request,
            organization_id: UUID | None = Query(default=None),  # noqa: B008, FAST002
            organization_slug: str | None = Query(default=None),  # noqa: FAST002
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> OrganizationFullView | None:
            _ = GetFullOrganizationQuery(
                organization_id=organization_id,
                organization_slug=organization_slug,
            )
            user = await organization.client.get_user(SecurityScopes(), request)
            current_session = await organization.client.get_session(request)
            resolved_organization_id = organization_id
            if resolved_organization_id is None and organization_slug is not None:
                by_slug = await organization.adapter.get_organization_by_slug(
                    organization.client.db,
                    organization_slug,
                )
                if by_slug is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="organization not found",
                    )
                resolved_organization_id = by_slug.id
            if resolved_organization_id is None:
                resolved_organization_id = _get_active_organization_id(current_session)
            if resolved_organization_id is None:
                return None

            member = await organization.adapter.get_member(
                organization.client.db,
                organization_id=resolved_organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )

            full_organization = await organization.get_full_organization(
                organization_id=resolved_organization_id,
            )
            if full_organization is None:
                return None
            org_row, members, invitations = full_organization
            return OrganizationFullView(
                organization=OrganizationView.model_validate(org_row),
                members=[MemberView.model_validate(row) for row in members],
                invitations=[InvitationView.model_validate(row) for row in invitations],
            )

        @router.get("/active-member", response_model=MemberView)
        async def get_active_member(
            request: Request,
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> MemberView:
            user = await organization.client.get_user(SecurityScopes(), request)
            current_session = await organization.client.get_session(request)
            organization_id = _get_active_organization_id(current_session)
            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="no active organization",
                )
            member = await organization.adapter.get_member(
                organization.client.db,
                organization_id=organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="member not found",
                )
            return MemberView.model_validate(member)

        @router.post("/invite-member", response_model=InvitationView)
        async def invite_member(
            body: InviteMemberBody,
            request: Request,
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> InvitationView:
            user = await organization.client.get_user(SecurityScopes(), request)
            current_session = await organization.client.get_session(request)
            organization_id = body.organization_id or _get_active_organization_id(current_session)
            if organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization_id is required",
                )
            member = await organization.adapter.get_member(
                organization.client.db,
                organization_id=organization_id,
                user_id=user.id,
            )
            if member is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not a member of this organization",
                )

            existing = await organization.adapter.get_pending_invitation(
                organization.client.db,
                organization_id=organization_id,
                email=body.email,
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="user is already invited to this organization",
                )

            invitation = await organization.create_invitation(
                organization_id=organization_id,
                email=body.email,
                role=body.role,
                inviter_id=user.id,
            )
            organization_row = await organization.adapter.get_organization_by_id(
                organization.client.db,
                organization_id,
            )
            if self._settings.send_invitation_email and organization_row is not None:
                await self._settings.send_invitation_email(invitation, organization_row)
            return InvitationView.model_validate(invitation)

        @router.post("/accept-invitation", response_model=AcceptInvitationView)
        async def accept_invitation(
            body: AcceptInvitationBody,
            request: Request,
            organization: OrganizationClient = Depends(self),  # noqa: B008, FAST002
        ) -> AcceptInvitationView:
            user = await organization.client.get_user(SecurityScopes(), request)
            current_session = await organization.client.get_session(request)
            invitation = await organization.adapter.get_invitation(
                organization.client.db,
                body.invitation_id,
            )
            if invitation is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="invitation not found",
                )
            if invitation.status != "pending" or invitation.expires_at < datetime.now(UTC):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="invitation is no longer valid",
                )
            if invitation.email.lower() != user.email.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="you are not the recipient of this invitation",
                )

            member = await organization.adapter.get_member(
                organization.client.db,
                organization_id=invitation.organization_id,
                user_id=user.id,
            )
            if member is None:
                member = await organization.adapter.create_member(
                    organization.client.db,
                    organization_id=invitation.organization_id,
                    user_id=user.id,
                    role=invitation.role,
                )
            accepted_invitation = await organization.adapter.set_invitation_status(
                organization.client.db,
                invitation_id=invitation.id,
                status="accepted",
            )
            if accepted_invitation is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="failed to update invitation status",
                )
            await organization.set_active_organization(
                session_id=current_session.id,
                organization_id=invitation.organization_id,
            )
            return AcceptInvitationView(
                invitation=InvitationView.model_validate(accepted_invitation),
                member=MemberView.model_validate(member),
            )

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
