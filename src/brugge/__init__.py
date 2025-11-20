"""Brugge - Modern authentication for FastAPI."""

__version__ = "0.1.0"

# Re-export everything from brugge.auth for convenience
from brugge.auth import (
    AccountProtocol,
    AlchemyAdapter,
    Auth,
    AuthenticationError,
    AuthorizationError,
    AuthSettings,
    BruggeError,
    ConfigurationError,
    CookieSettings,
    generate_session_id,
    generate_state_token,
    GoogleOAuthProvider,
    GoogleOAuthSettings,
    GoogleTokenResponse,
    GoogleUserInfo,
    InvalidStateError,
    OAuthError,
    OAuthStateProtocol,
    parse_scopes,
    SessionExpiredError,
    SessionManager,
    SessionProtocol,
    SessionSettings,
    URLSettings,
    UserProtocol,
    validate_scopes,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "Auth",
    "AuthSettings",
    # Adapters
    "AlchemyAdapter",
    # Session
    "SessionManager",
    # Providers
    "GoogleOAuthProvider",
    "GoogleTokenResponse",
    "GoogleUserInfo",
    # Settings
    "SessionSettings",
    "CookieSettings",
    "GoogleOAuthSettings",
    "URLSettings",
    # Protocols
    "UserProtocol",
    "AccountProtocol",
    "SessionProtocol",
    "OAuthStateProtocol",
    # Exceptions
    "BruggeError",
    "AuthenticationError",
    "AuthorizationError",
    "SessionExpiredError",
    "InvalidStateError",
    "OAuthError",
    "ConfigurationError",
    # Utils
    "generate_session_id",
    "generate_state_token",
    "parse_scopes",
    "validate_scopes",
]
