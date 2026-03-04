import pytest

import belgie


def test_version_export() -> None:
    assert hasattr(belgie, "__version__")
    assert isinstance(belgie.__version__, str)


def test_core_exports() -> None:
    assert hasattr(belgie, "Belgie")
    assert hasattr(belgie, "BelgieSettings")
    assert hasattr(belgie, "DatabaseProtocol")


def test_adapter_exports() -> None:
    try:
        from belgie import BelgieAdapter  # noqa: PLC0415
    except ImportError:
        return

    assert BelgieAdapter is not None


def test_old_adapter_export_removed() -> None:
    with pytest.raises(ImportError):
        from belgie import AlchemyAdapter  # noqa: PLC0415, F401


def test_adapter_module_exports() -> None:
    try:
        from belgie.alchemy.adapter import BelgieAdapter  # noqa: PLC0415
    except ImportError:
        return

    assert BelgieAdapter is not None


def test_mixins_module_exports() -> None:
    try:
        from belgie.alchemy.mixins import (  # noqa: PLC0415
            AccountMixin,
            OAuthStateMixin,
            SessionMixin,
            UserMixin,
        )
    except ImportError:
        return

    assert AccountMixin is not None
    assert OAuthStateMixin is not None
    assert SessionMixin is not None
    assert UserMixin is not None


def test_mixins_exports_from_alchemy_module() -> None:
    try:
        from belgie.alchemy import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin  # noqa: PLC0415
    except ImportError:
        return

    assert AccountMixin is not None
    assert OAuthStateMixin is not None
    assert SessionMixin is not None
    assert UserMixin is not None


def test_old_alchemy_module_export_removed() -> None:
    with pytest.raises(ImportError):
        from belgie.alchemy import AlchemyAdapter  # noqa: PLC0415, F401


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


def test_protocol_exports() -> None:
    from belgie import proto  # noqa: PLC0415

    assert hasattr(proto, "UserProtocol")
    assert hasattr(proto, "AccountProtocol")
    assert hasattr(proto, "DatabaseProtocol")
    assert hasattr(proto, "SessionProtocol")
    assert hasattr(proto, "OAuthStateProtocol")


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
        DatabaseProtocol,
        SessionManager,
    )

    assert Belgie is not None
    assert BelgieSettings is not None
    assert DatabaseProtocol is not None
    assert SessionManager is not None
