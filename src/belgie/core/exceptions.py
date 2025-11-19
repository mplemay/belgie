class BelgieException(Exception):
    pass


class AuthenticationError(BelgieException):
    pass


class AuthorizationError(BelgieException):
    pass


class SessionExpiredError(AuthenticationError):
    pass


class InvalidStateError(BelgieException):
    pass


class OAuthError(BelgieException):
    pass


class ConfigurationError(BelgieException):
    pass
