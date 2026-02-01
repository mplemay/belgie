"""Belgie Auth - Authentication components."""

from belgie_proto import DBConnection

from belgie.auth.core.auth import Auth
from belgie.auth.core.client import AuthClient
from belgie.auth.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BelgieError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)
from belgie.auth.core.hooks import HookContext, HookEvent, HookRunner, Hooks
from belgie.auth.core.settings import (
    AuthSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from belgie.auth.providers import OAuthProviderProtocol, Providers
from belgie.auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings, GoogleUserInfo
from belgie.auth.session.manager import SessionManager
from belgie.auth.utils.crypto import generate_session_id, generate_state_token
from belgie.auth.utils.scopes import parse_scopes, validate_scopes

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
