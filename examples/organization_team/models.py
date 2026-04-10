from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie.alchemy.mixins import (
    AccountMixin,
    IndividualMixin,
    OAuthAccountMixin,
    OAuthStateMixin,
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
    SessionMixin,
    TeamMemberMixin,
    TeamMixin,
)


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Individual(IndividualMixin, Account):
    pass


class OAuthAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


class Organization(OrganizationMixin, Account):
    pass


class OrganizationMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMemberMixin):
    pass


class OrganizationInvitation(
    DataclassBase,
    PrimaryKeyMixin,
    TimestampMixin,
    OrganizationInvitationMixin,
):
    pass


class Team(TeamMixin, Account):
    pass


class TeamMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMemberMixin):
    pass


__all__ = [
    "Account",
    "Individual",
    "OAuthAccount",
    "OAuthState",
    "Organization",
    "OrganizationInvitation",
    "OrganizationMember",
    "Session",
    "Team",
    "TeamMember",
]
