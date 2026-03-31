from __future__ import annotations

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


class Organization(OrganizationMixin, Customer):
    pass


class OrganizationMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMemberMixin):
    pass


class OrganizationInvitation(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationInvitationMixin):
    pass


class Team(TeamMixin, Customer):
    pass


class TeamMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMemberMixin):
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
