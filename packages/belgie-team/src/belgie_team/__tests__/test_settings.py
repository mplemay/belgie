from __future__ import annotations

from collections.abc import Awaitable, Callable  # noqa: TC003

import pytest
from belgie_proto.team import TeamAdapterProtocol
from pydantic import ValidationError

from belgie_team.__tests__.fakes import (
    FakeInvitationRow,
    FakeMemberRow,
    FakeOrganizationRow,
    FakeTeamMemberRow,
    FakeTeamRow,
)
from belgie_team.settings import Team


class FakeTeamAdapter(
    TeamAdapterProtocol[
        FakeOrganizationRow,
        FakeMemberRow,
        FakeInvitationRow,
        FakeTeamRow,
        FakeTeamMemberRow,
    ],
):
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            msg = "unexpected adapter call in Team settings test"
            raise AssertionError(msg)

        return _unexpected


def test_team_settings_requires_adapter() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Team()

    assert "adapter" in str(exc_info.value)


def test_team_settings_rejects_invalid_adapter() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Team(adapter=object())

    assert "TeamAdapterProtocol" in str(exc_info.value)


def test_team_settings_accepts_team_adapter_protocol() -> None:
    adapter = FakeTeamAdapter()

    settings = Team(adapter=adapter)

    assert settings.adapter is adapter
