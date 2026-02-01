"""Belgie - Modern authentication and analytics for FastAPI."""

from auth import (
    Auth,
    AuthClient,
    AuthenticationError,
    AuthorizationError,
    AuthSettings,
    BelgieError,
    ConfigurationError,
    CookieSettings,
    DBConnection,
    GoogleOAuthProvider,
    GoogleProviderSettings,
    GoogleUserInfo,
    HookContext,
    HookEvent,
    HookRunner,
    Hooks,
    InvalidStateError,
    OAuthError,
    OAuthProviderProtocol,
    Providers,
    SessionExpiredError,
    SessionManager,
    SessionSettings,
    URLSettings,
    generate_session_id,
    generate_state_token,
    parse_scopes,
    validate_scopes,
)

from belgie.alchemy import AlchemyAdapter

__version__ = "0.1.0"

__all__ = [  # noqa: RUF022
    # Version
    "__version__",
    # Core
    "Auth",
    "AuthClient",
    "AuthSettings",
    "Hooks",
    "HookContext",
    "HookEvent",
    "HookRunner",
    # Adapters
    "AlchemyAdapter",
    "DBConnection",
    # Session
    "SessionManager",
    # Providers
    "GoogleOAuthProvider",
    "GoogleProviderSettings",
    "GoogleUserInfo",
    "OAuthProviderProtocol",
    "Providers",
    # Settings
    "SessionSettings",
    "CookieSettings",
    "URLSettings",
    # Exceptions
    "BelgieError",
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
