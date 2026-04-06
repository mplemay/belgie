import pytest

import belgie


def test_version_export() -> None:
    assert hasattr(belgie, "__version__")
    assert isinstance(belgie.__version__, str)


def test_core_exports() -> None:
    assert hasattr(belgie, "Belgie")
    assert hasattr(belgie, "BelgieSettings")


def test_adapter_exports() -> None:
    try:
        from belgie import BelgieAdapter  # noqa: PLC0415
    except ImportError:
        return

    assert BelgieAdapter is not None


def test_old_adapter_export_removed() -> None:
    with pytest.raises(ImportError):
        from belgie import AlchemyAdapter  # noqa: PLC0415, F401


def test_adapter_exports_from_alchemy_module() -> None:
    try:
        from belgie.alchemy import BelgieAdapter  # noqa: PLC0415
    except ImportError:
        return

    assert BelgieAdapter is not None


def test_team_adapter_exports_from_domain_module() -> None:
    try:
        from belgie.alchemy.team import TeamAdapter  # noqa: PLC0415
    except ImportError:
        return

    assert TeamAdapter is not None


def test_organization_adapter_exports_from_domain_module() -> None:
    try:
        from belgie.alchemy.organization import OrganizationAdapter  # noqa: PLC0415
    except ImportError:
        return

    assert OrganizationAdapter is not None


def test_old_adapter_module_removed() -> None:
    try:
        import belgie.alchemy  # noqa: PLC0415, F401
    except ImportError:
        return

    with pytest.raises(ModuleNotFoundError):
        from belgie.alchemy.adapter import BelgieAdapter  # noqa: PLC0415, F401


def test_mixins_module_exports() -> None:
    try:
        from belgie.alchemy.mixins import (  # noqa: PLC0415
            IndividualMixin,
            OAuthAccountMixin,
            OAuthStateMixin,
            SessionMixin,
        )
    except ImportError:
        return

    assert OAuthAccountMixin is not None
    assert OAuthStateMixin is not None
    assert SessionMixin is not None
    assert IndividualMixin is not None


def test_mixins_exports_from_alchemy_module() -> None:
    try:
        from belgie.alchemy import IndividualMixin, OAuthAccountMixin, OAuthStateMixin, SessionMixin  # noqa: PLC0415
    except ImportError:
        return

    assert OAuthAccountMixin is not None
    assert OAuthStateMixin is not None
    assert SessionMixin is not None
    assert IndividualMixin is not None


def test_old_alchemy_module_export_removed() -> None:
    with pytest.raises(ImportError):
        from belgie.alchemy import AlchemyAdapter  # noqa: PLC0415, F401


def test_team_and_organization_adapters_not_exported_from_alchemy_module() -> None:
    try:
        from belgie import alchemy  # noqa: PLC0415
    except ImportError:
        return

    assert not hasattr(alchemy, "TeamAdapter")
    assert not hasattr(alchemy, "OrganizationAdapter")


def test_session_exports() -> None:
    assert hasattr(belgie, "SessionManager")


def test_settings_exports() -> None:
    assert hasattr(belgie, "SessionSettings")
    assert hasattr(belgie, "CookieSettings")
    assert hasattr(belgie, "URLSettings")


def test_hook_exports_removed() -> None:
    assert not hasattr(belgie, "Hooks")
    assert not hasattr(belgie, "HookContext")
    assert not hasattr(belgie, "HookEvent")
    assert not hasattr(belgie, "HookRunner")
    assert not hasattr(belgie, "PreSignupContext")


def test_direct_hook_imports_fail() -> None:
    with pytest.raises(ImportError):
        from belgie import Hooks  # noqa: PLC0415, F401


def test_protocol_exports_from_domain_modules() -> None:
    from belgie.proto.core import (  # noqa: PLC0415
        AdapterProtocol,
        IndividualProtocol,
        OAuthAccountProtocol,
        OAuthStateProtocol,
        SessionProtocol,
    )
    from belgie.proto.organization import (  # noqa: PLC0415
        InvitationProtocol,
        MemberProtocol,
        OrganizationAdapterProtocol,
        OrganizationProtocol,
    )
    from belgie.proto.team import (  # noqa: PLC0415
        TeamAdapterProtocol,
        TeamMemberProtocol,
        TeamProtocol,
    )

    assert OAuthAccountProtocol is not None
    assert AdapterProtocol is not None
    assert OAuthStateProtocol is not None
    assert SessionProtocol is not None
    assert IndividualProtocol is not None
    assert InvitationProtocol is not None
    assert MemberProtocol is not None
    assert OrganizationAdapterProtocol is not None
    assert OrganizationProtocol is not None
    assert TeamAdapterProtocol is not None
    assert TeamMemberProtocol is not None
    assert TeamProtocol is not None


def test_removed_team_and_organization_session_exports() -> None:
    from belgie.alchemy import mixins  # noqa: PLC0415
    from belgie.proto import organization, team  # noqa: PLC0415

    assert not hasattr(organization, "OrganizationSessionProtocol")
    assert not hasattr(team, "TeamSessionProtocol")
    assert not hasattr(mixins, "OrganizationSessionMixin")
    assert not hasattr(mixins, "TeamSessionMixin")


def test_flat_proto_reexports_removed() -> None:
    from belgie import proto  # noqa: PLC0415

    assert not hasattr(proto, "IndividualProtocol")
    assert not hasattr(proto, "AdapterProtocol")
    assert not hasattr(proto, "TeamAdapterProtocol")


def test_exception_exports() -> None:
    assert hasattr(belgie, "BelgieError")
    assert hasattr(belgie, "AuthenticationError")
    assert hasattr(belgie, "AuthorizationError")
    assert hasattr(belgie, "SessionExpiredError")
    assert hasattr(belgie, "InvalidStateError")
    assert hasattr(belgie, "OAuthError")
    assert hasattr(belgie, "ConfigurationError")


def test_util_exports() -> None:
    assert hasattr(belgie, "generate_session_id")
    assert hasattr(belgie, "generate_state_token")
    assert hasattr(belgie, "parse_scopes")
    assert hasattr(belgie, "validate_scopes")


def test_all_exports_present() -> None:
    for name in belgie.__all__:
        if name == "BelgieAdapter":
            try:
                assert getattr(belgie, name) is not None
            except ImportError:
                continue
            continue

        assert hasattr(belgie, name), f"Missing export: {name}"


def test_direct_imports() -> None:
    from belgie import (  # noqa: PLC0415
        Belgie,
        BelgieSettings,
        SessionManager,
    )

    assert Belgie is not None
    assert BelgieSettings is not None
    assert SessionManager is not None
