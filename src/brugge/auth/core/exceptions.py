class BruggeError(Exception):
    pass


class AuthenticationError(BruggeError):
    pass


class AuthorizationError(BruggeError):
    pass


class SessionExpiredError(AuthenticationError):
    pass


class InvalidStateError(BruggeError):
    pass


class OAuthError(BruggeError):
    pass


class ConfigurationError(BruggeError):
    pass
