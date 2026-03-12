from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie.alchemy.mixins import (
    AccountMixin,
    OAuthStateMixin,
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
    SessionMixin,
    TeamMemberMixin,
    TeamMixin,
    UserMixin,
)


class User(DataclassBase, PrimaryKeyMixin, TimestampMixin, UserMixin):
    pass


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


class Organization(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMixin):
    pass


class OrganizationMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMemberMixin):
    pass


class OrganizationInvitation(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationInvitationMixin):
    pass


class Team(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMixin):
    pass


class TeamMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMemberMixin):
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
