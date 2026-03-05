from __future__ import annotations

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_organization.plugin import OrganizationPlugin
from belgie_organization.settings import Organization
from belgie_proto.organization import OrganizationAdapterProtocol
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.organization import OrganizationProtocol


class _ProtocolOrganizationAdapter(OrganizationAdapterProtocol):
    pass


def _build_settings() -> Organization:
    Organization.model_rebuild(
        _types_namespace={
            "InvitationProtocol": InvitationProtocol,
            "OrganizationProtocol": OrganizationProtocol,
        },
    )
    return Organization()


def test_settings_call_rejects_non_organization_adapter() -> None:
    settings = _build_settings()
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")

    with pytest.raises(TypeError, match=r"OrganizationAdapterProtocol"):
        settings(belgie_settings, object())


def test_settings_call_accepts_organization_adapter_protocol() -> None:
    settings = _build_settings()
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")

    plugin = settings(belgie_settings, _ProtocolOrganizationAdapter())

    assert isinstance(plugin, OrganizationPlugin)
