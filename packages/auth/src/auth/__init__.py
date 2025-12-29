"""Belgie Auth - Authentication components."""

from auth.adapters.alchemy import AlchemyAdapter
from auth.adapters.protocols import (
    AccountProtocol,
    AdapterProtocol,
    OAuthStateProtocol,
    SessionProtocol,
    UserProtocol,
)
from auth.core.auth import Auth
from auth.core.client import AuthClient
from auth.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BelgieError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)
from auth.core.hooks import HookContext, HookEvent, HookRunner, Hooks
from auth.core.settings import (
    AuthSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from auth.providers import OAuthProviderProtocol, Providers
from auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings, GoogleUserInfo
from auth.session.manager import SessionManager
from auth.utils.crypto import generate_session_id, generate_state_token
from auth.utils.scopes import parse_scopes, validate_scopes

__all__ = [  # noqa: RUF022
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
    # Protocols
    "UserProtocol",
    "AdapterProtocol",
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
