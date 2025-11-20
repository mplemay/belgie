class BelgieError(Exception):
    pass


class AuthenticationError(BelgieError):
    pass


class AuthorizationError(BelgieError):
    pass


class SessionExpiredError(AuthenticationError):
    pass


class InvalidStateError(BelgieError):
    pass


class OAuthError(BelgieError):
    pass


class ConfigurationError(BelgieError):
    pass
