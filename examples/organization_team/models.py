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
    CustomerMixin,
    IndividualMixin,
    OAuthStateMixin,
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
    SessionMixin,
    TeamMemberMixin,
    TeamMixin,
)


class Customer(DataclassBase, PrimaryKeyMixin, TimestampMixin, CustomerMixin):
    pass


class Individual(IndividualMixin, Customer):
    pass


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


class Organization(OrganizationMixin, Customer, OrganizationProtocol):
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


class Team(TeamMixin, Customer, TeamProtocol):
    pass


class TeamMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMemberMixin, TeamMemberProtocol):
    pass


__all__ = [
    "Account",
    "Customer",
    "Individual",
    "OAuthState",
    "Organization",
    "OrganizationInvitation",
    "OrganizationMember",
    "Session",
    "Team",
    "TeamMember",
]
