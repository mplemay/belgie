from __future__ import annotations

from brussels.base import DataclassBase

from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin


class Team(DataclassBase, TeamMixin):
    pass


class TeamMember(DataclassBase, TeamMemberMixin):
    pass
