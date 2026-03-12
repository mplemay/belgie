from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie_alchemy.__tests__.fixtures.core.models import Account, OAuthState, Session, User  # noqa: F401
from belgie_alchemy.organization.mixins import (
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
)


class Organization(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMixin):
    pass


class OrganizationMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMemberMixin):
    pass


class OrganizationInvitation(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationInvitationMixin):
    pass
