from __future__ import annotations

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_proto.team import TeamAdapterProtocol

from belgie_team.plugin import TeamPlugin
from belgie_team.settings import Team


class _ProtocolTeamAdapter(TeamAdapterProtocol):
    pass


def test_settings_call_rejects_non_team_adapter() -> None:
    settings = Team()
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")

    with pytest.raises(TypeError, match=r"TeamAdapterProtocol"):
        settings(belgie_settings, object())


def test_settings_call_accepts_team_adapter_protocol() -> None:
    settings = Team()
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")

    plugin = settings(belgie_settings, _ProtocolTeamAdapter())

    assert isinstance(plugin, TeamPlugin)
