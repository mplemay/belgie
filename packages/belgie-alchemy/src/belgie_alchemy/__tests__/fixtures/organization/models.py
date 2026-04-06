from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie_alchemy.__tests__.fixtures.core.models import (  # noqa: F401
    Account,
    Individual,
    OAuthAccount,
    OAuthState,
    Session,
)
from belgie_alchemy.organization.mixins import (
    OrganizationInvitationMixin,
    OrganizationMemberMixin,
    OrganizationMixin,
)


class Organization(OrganizationMixin, Account):
    pass


class OrganizationMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationMemberMixin):
    pass


class OrganizationInvitation(DataclassBase, PrimaryKeyMixin, TimestampMixin, OrganizationInvitationMixin):
    pass
