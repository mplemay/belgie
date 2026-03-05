from __future__ import annotations

from collections.abc import Awaitable, Callable  # noqa: TC003

import pytest
from belgie_proto.organization import OrganizationAdapterProtocol
from pydantic import ValidationError

from belgie_organization.settings import Organization


class FakeOrganizationAdapter(OrganizationAdapterProtocol):
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            msg = "unexpected adapter call in Organization settings test"
            raise AssertionError(msg)

        return _unexpected


def test_organization_settings_requires_adapter() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Organization()

    assert "adapter" in str(exc_info.value)


def test_organization_settings_rejects_invalid_adapter() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Organization(adapter=object())

    assert "OrganizationAdapterProtocol" in str(exc_info.value)


def test_organization_settings_accepts_adapter_protocol() -> None:
    adapter = FakeOrganizationAdapter()

    settings = Organization(adapter=adapter)

    assert settings.adapter is adapter
