import belgie


def test_version_export() -> None:
    assert hasattr(belgie, "__version__")
    assert isinstance(belgie.__version__, str)


def test_core_exports() -> None:
    assert hasattr(belgie, "Auth")
    assert hasattr(belgie, "AuthSettings")


def test_adapter_exports() -> None:
    assert hasattr(belgie, "AlchemyAdapter")


def test_session_exports() -> None:
    assert hasattr(belgie, "SessionManager")


def test_provider_exports() -> None:
    assert hasattr(belgie, "GoogleOAuthProvider")
    assert hasattr(belgie, "GoogleTokenResponse")
    assert hasattr(belgie, "GoogleUserInfo")


def test_settings_exports() -> None:
    assert hasattr(belgie, "SessionSettings")
    assert hasattr(belgie, "CookieSettings")
    assert hasattr(belgie, "GoogleOAuthSettings")
    assert hasattr(belgie, "URLSettings")


def test_protocol_exports() -> None:
    assert hasattr(belgie, "UserProtocol")
    assert hasattr(belgie, "AccountProtocol")
    assert hasattr(belgie, "SessionProtocol")
    assert hasattr(belgie, "OAuthStateProtocol")


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
        assert hasattr(belgie, name), f"Missing export: {name}"


def test_direct_imports() -> None:
    from belgie import (  # noqa: PLC0415
        AlchemyAdapter,
        Auth,
        AuthSettings,
        GoogleOAuthProvider,
        SessionManager,
    )

    assert Auth is not None
    assert AuthSettings is not None
    assert AlchemyAdapter is not None
    assert SessionManager is not None
    assert GoogleOAuthProvider is not None
