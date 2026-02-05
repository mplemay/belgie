"""Belgie Core - Authentication components."""

from belgie_proto import DBConnection

from belgie_core.core.belgie import Belgie
from belgie_core.core.client import BelgieClient
from belgie_core.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BelgieError,
    ConfigurationError,
    InvalidStateError,
    OAuthError,
    SessionExpiredError,
)
from belgie_core.core.hooks import HookContext, HookEvent, HookRunner, Hooks, PreSignupContext
from belgie_core.core.settings import (
    BelgieSettings,
    CookieSettings,
    SessionSettings,
    URLSettings,
)
from belgie_core.session.manager import SessionManager
from belgie_core.utils.crypto import generate_session_id, generate_state_token
from belgie_core.utils.scopes import parse_scopes, validate_scopes

__all__ = [  # noqa: RUF022
    # Core
    "Belgie",
    "BelgieClient",
    "BelgieSettings",
    "Hooks",
    "HookContext",
    "PreSignupContext",
    "HookEvent",
    "HookRunner",
    # Adapters
    "DBConnection",
    # Session
    "SessionManager",
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
