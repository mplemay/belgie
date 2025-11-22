"""Belgie Auth - Authentication components."""

from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.core.auth import Auth
from belgie.auth.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BelgieError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)
from belgie.auth.core.settings import (
    AuthSettings,
    CookieSettings,
    GoogleOAuthSettings,
    SessionSettings,
    URLSettings,
)
from belgie.auth.protocols.models import (
    AccountProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from belgie.auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings, GoogleUserInfo
from belgie.auth.session.manager import SessionManager
from belgie.auth.utils.crypto import generate_session_id, generate_state_token
from belgie.auth.utils.scopes import parse_scopes, validate_scopes

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
    "GoogleProviderSettings",
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
]
