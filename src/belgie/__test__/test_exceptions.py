import pytest

from belgie.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BelgieError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)


def test_belgie_error_is_exception() -> None:
    assert issubclass(BelgieError, Exception)


def test_authentication_error_is_belgie_error() -> None:
    assert issubclass(AuthenticationError, BelgieError)


def test_authorization_error_is_belgie_error() -> None:
    assert issubclass(AuthorizationError, BelgieError)


def test_session_expired_error_is_authentication_error() -> None:
    assert issubclass(SessionExpiredError, AuthenticationError)
    assert issubclass(SessionExpiredError, BelgieError)


def test_invalid_state_error_is_belgie_error() -> None:
    assert issubclass(InvalidStateError, BelgieError)


def test_oauth_error_is_belgie_error() -> None:
    assert issubclass(OAuthError, BelgieError)


def test_configuration_error_is_belgie_error() -> None:
    assert issubclass(ConfigurationError, BelgieError)


def test_can_raise_and_catch_authentication_error() -> None:
    msg = "test message"
    with pytest.raises(AuthenticationError, match=msg):
        raise AuthenticationError(msg)


def test_can_catch_session_expired_as_authentication_error() -> None:
    msg = "session expired"
    with pytest.raises(AuthenticationError):
        raise SessionExpiredError(msg)


def test_can_catch_all_as_belgie_error() -> None:
    msg1 = "insufficient scopes"
    with pytest.raises(BelgieError):
        raise AuthorizationError(msg1)

    msg2 = "oauth failed"
    with pytest.raises(BelgieError):
        raise OAuthError(msg2)

    msg3 = "invalid config"
    with pytest.raises(BelgieError):
        raise ConfigurationError(msg3)
