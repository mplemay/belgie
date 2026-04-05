from __future__ import annotations

from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol
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


class Organization(OrganizationMixin, Account, OrganizationProtocol):
    pass


class OrganizationMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMemberMixin, MemberProtocol):
    pass


class OrganizationInvitation(
    DataclassBase,
    PrimaryKeyMixin,
    TimestampMixin,
    OrganizationInvitationMixin,
    InvitationProtocol,
):
    pass


class Team(TeamMixin, Account, TeamProtocol):
    pass


class TeamMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMemberMixin, TeamMemberProtocol):
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
