import pytest

from brugge.auth.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BruggeError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)


def test_belgie_error_is_exception() -> None:
    assert issubclass(BruggeError, Exception)


def test_authentication_error_is_belgie_error() -> None:
    assert issubclass(AuthenticationError, BruggeError)


def test_authorization_error_is_belgie_error() -> None:
    assert issubclass(AuthorizationError, BruggeError)


def test_session_expired_error_is_authentication_error() -> None:
    assert issubclass(SessionExpiredError, AuthenticationError)
    assert issubclass(SessionExpiredError, BruggeError)


def test_invalid_state_error_is_belgie_error() -> None:
    assert issubclass(InvalidStateError, BruggeError)


def test_oauth_error_is_belgie_error() -> None:
    assert issubclass(OAuthError, BruggeError)


def test_configuration_error_is_belgie_error() -> None:
    assert issubclass(ConfigurationError, BruggeError)


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
    with pytest.raises(BruggeError):
        raise AuthorizationError(msg1)

    msg2 = "oauth failed"
    with pytest.raises(BruggeError):
        raise OAuthError(msg2)

    msg3 = "invalid config"
    with pytest.raises(BruggeError):
        raise ConfigurationError(msg3)
