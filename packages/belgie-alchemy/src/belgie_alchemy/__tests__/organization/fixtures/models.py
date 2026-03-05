from __future__ import annotations

from brussels.base import DataclassBase

from belgie_alchemy.__tests__.core.fixtures.models import Account, OAuthState, Session, User  # noqa: F401
from belgie_alchemy.organization.mixins import (
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
)


class Organization(DataclassBase, OrganizationMixin):
    pass


class OrganizationMember(DataclassBase, OrganizationMemberMixin):
    pass


class OrganizationInvitation(DataclassBase, OrganizationInvitationMixin):
    pass
