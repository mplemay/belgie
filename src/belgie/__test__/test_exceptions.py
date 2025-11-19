import pytest

from belgie.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BelgieException,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)


def test_belgie_exception_is_exception() -> None:
    assert issubclass(BelgieException, Exception)


def test_authentication_error_is_belgie_exception() -> None:
    assert issubclass(AuthenticationError, BelgieException)


def test_authorization_error_is_belgie_exception() -> None:
    assert issubclass(AuthorizationError, BelgieException)


def test_session_expired_error_is_authentication_error() -> None:
    assert issubclass(SessionExpiredError, AuthenticationError)
    assert issubclass(SessionExpiredError, BelgieException)


def test_invalid_state_error_is_belgie_exception() -> None:
    assert issubclass(InvalidStateError, BelgieException)


def test_oauth_error_is_belgie_exception() -> None:
    assert issubclass(OAuthError, BelgieException)


def test_configuration_error_is_belgie_exception() -> None:
    assert issubclass(ConfigurationError, BelgieException)


def test_can_raise_and_catch_authentication_error() -> None:
    with pytest.raises(AuthenticationError, match="test message"):
        raise AuthenticationError("test message")


def test_can_catch_session_expired_as_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        raise SessionExpiredError("session expired")


def test_can_catch_all_as_belgie_exception() -> None:
    with pytest.raises(BelgieException):
        raise AuthorizationError("insufficient scopes")

    with pytest.raises(BelgieException):
        raise OAuthError("oauth failed")

    with pytest.raises(BelgieException):
        raise ConfigurationError("invalid config")
