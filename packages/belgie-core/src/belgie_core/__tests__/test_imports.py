import belgie


def test_version_export() -> None:
    assert hasattr(belgie, "__version__")
    assert isinstance(belgie.__version__, str)


def test_core_exports() -> None:
    assert hasattr(belgie, "Belgie")
    assert hasattr(belgie, "BelgieSettings")


def test_adapter_exports() -> None:
    try:
        from belgie import AlchemyAdapter  # noqa: PLC0415
    except ImportError:
        return

    assert AlchemyAdapter is not None


def test_session_exports() -> None:
    assert hasattr(belgie, "SessionManager")


def test_provider_exports() -> None:
    assert hasattr(belgie, "GoogleOAuthProvider")
    assert hasattr(belgie, "GoogleProviderSettings")
    assert hasattr(belgie, "GoogleUserInfo")


def test_settings_exports() -> None:
    assert hasattr(belgie, "SessionSettings")
    assert hasattr(belgie, "CookieSettings")
    assert hasattr(belgie, "URLSettings")


def test_hook_exports() -> None:
    assert hasattr(belgie, "Hooks")
    assert hasattr(belgie, "HookContext")
    assert hasattr(belgie, "HookEvent")
    assert hasattr(belgie, "HookRunner")


def test_protocol_exports() -> None:
    from belgie import proto  # noqa: PLC0415

    assert hasattr(proto, "UserProtocol")
    assert hasattr(proto, "AccountProtocol")
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
        if name == "AlchemyAdapter":
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
        GoogleOAuthProvider,
        SessionManager,
    )

    assert Belgie is not None
    assert BelgieSettings is not None
    assert SessionManager is not None
    assert GoogleOAuthProvider is not None
