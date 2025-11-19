from belgie.adapters.alchemy import AlchemyAdapter
from belgie.core.auth import Auth
from belgie.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BelgieError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)
from belgie.core.settings import (
    AuthSettings,
    CookieSettings,
    GoogleOAuthSettings,
    SessionSettings,
    URLSettings,
)
from belgie.protocols.models import (
    AccountProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from belgie.providers.google import GoogleOAuthProvider, GoogleTokenResponse, GoogleUserInfo
from belgie.session.manager import SessionManager
from belgie.utils.crypto import generate_session_id, generate_state_token
from belgie.utils.scopes import parse_scopes, validate_scopes

__version__ = "0.1.0"

__all__ = [  # noqa: RUF022
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
    # Version
    "__version__",
]
