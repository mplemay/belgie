"""Brugge Auth - Authentication components."""

from brugge.auth.adapters.alchemy import AlchemyAdapter
from brugge.auth.core.auth import Auth
from brugge.auth.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BruggeError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)
from brugge.auth.core.settings import (
    AuthSettings,
    CookieSettings,
    GoogleOAuthSettings,
    SessionSettings,
    URLSettings,
)
from brugge.auth.protocols.models import (
    AccountProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from brugge.auth.providers.google import GoogleOAuthProvider, GoogleTokenResponse, GoogleUserInfo
from brugge.auth.session.manager import SessionManager
from brugge.auth.utils.crypto import generate_session_id, generate_state_token
from brugge.auth.utils.scopes import parse_scopes, validate_scopes

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
