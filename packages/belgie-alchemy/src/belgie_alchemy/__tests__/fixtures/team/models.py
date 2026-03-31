from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie_alchemy.__tests__.fixtures.core.models import Customer
from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin


class Team(TeamMixin, Customer):
    pass


class TeamMember(DataclassBase, PrimaryKeyMixin, TimestampMixin, TeamMemberMixin):
    pass
