from __future__ import annotations

from brussels.base import DataclassBase

from belgie.alchemy.mixins import (
    AccountMixin,
    OAuthStateMixin,
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
    OrganizationSessionMixin,
    SessionMixin,
    TeamMemberMixin,
    TeamMixin,
    TeamSessionMixin,
    UserMixin,
)


class User(DataclassBase, UserMixin):
    pass


class Account(DataclassBase, AccountMixin):
    pass


class Session(DataclassBase, SessionMixin, OrganizationSessionMixin, TeamSessionMixin):
    pass


class OAuthState(DataclassBase, OAuthStateMixin):
    pass


class Organization(DataclassBase, OrganizationMixin):
    pass


class OrganizationMember(DataclassBase, OrganizationMemberMixin):
    pass


class OrganizationInvitation(DataclassBase, OrganizationInvitationMixin):
    pass


class Team(DataclassBase, TeamMixin):
    pass


class TeamMember(DataclassBase, TeamMemberMixin):
    pass


__all__ = [
    "Account",
    "OAuthState",
    "Organization",
    "OrganizationInvitation",
    "OrganizationMember",
    "Session",
    "Team",
    "TeamMember",
    "User",
]
