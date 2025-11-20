import brugge


def test_version_export() -> None:
    assert hasattr(brugge, "__version__")
    assert isinstance(brugge.__version__, str)


def test_core_exports() -> None:
    assert hasattr(brugge, "Auth")
    assert hasattr(brugge, "AuthSettings")


def test_adapter_exports() -> None:
    assert hasattr(brugge, "AlchemyAdapter")


def test_session_exports() -> None:
    assert hasattr(brugge, "SessionManager")


def test_provider_exports() -> None:
    assert hasattr(brugge, "GoogleOAuthProvider")
    assert hasattr(brugge, "GoogleTokenResponse")
    assert hasattr(brugge, "GoogleUserInfo")


def test_settings_exports() -> None:
    assert hasattr(brugge, "SessionSettings")
    assert hasattr(brugge, "CookieSettings")
    assert hasattr(brugge, "GoogleOAuthSettings")
    assert hasattr(brugge, "URLSettings")


def test_protocol_exports() -> None:
    assert hasattr(brugge, "UserProtocol")
    assert hasattr(brugge, "AccountProtocol")
    assert hasattr(brugge, "SessionProtocol")
    assert hasattr(brugge, "OAuthStateProtocol")


def test_exception_exports() -> None:
    assert hasattr(brugge, "BruggeError")
    assert hasattr(brugge, "AuthenticationError")
    assert hasattr(brugge, "AuthorizationError")
    assert hasattr(brugge, "SessionExpiredError")
    assert hasattr(brugge, "InvalidStateError")
    assert hasattr(brugge, "OAuthError")
    assert hasattr(brugge, "ConfigurationError")


def test_util_exports() -> None:
    assert hasattr(brugge, "generate_session_id")
    assert hasattr(brugge, "generate_state_token")
    assert hasattr(brugge, "parse_scopes")
    assert hasattr(brugge, "validate_scopes")


def test_all_exports_present() -> None:
    for name in brugge.__all__:
        assert hasattr(brugge, name), f"Missing export: {name}"


def test_direct_imports() -> None:
    from brugge import (  # noqa: PLC0415
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
