from __future__ import annotations

from brussels.base import DataclassBase

from belgie_alchemy.__tests__.fixtures.models import Account, OAuthState, Session, User  # noqa: F401
from belgie_alchemy.mixins import (
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
    TeamMemberMixin,
    TeamMixin,
)


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
