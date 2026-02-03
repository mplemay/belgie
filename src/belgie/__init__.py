"""Belgie - Modern authentication and analytics for FastAPI."""

from importlib import import_module
from typing import TYPE_CHECKING

from belgie_core import (
    AuthenticationError,
    AuthorizationError,
    Belgie,
    BelgieClient,
    BelgieError,
    BelgieSettings,
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

if TYPE_CHECKING:
    from belgie_alchemy import AlchemyAdapter  # type: ignore[import-not-found]

__version__ = "0.1.0"

_ALCHEMY_IMPORT_ERROR = "AlchemyAdapter requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"


def __getattr__(name: str) -> object:
    if name != "AlchemyAdapter":
        msg = f"module 'belgie' has no attribute {name!r}"
        raise AttributeError(msg)

    try:
        module = import_module("belgie_alchemy")
    except ModuleNotFoundError as exc:
        raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

    return module.AlchemyAdapter


__all__ = [  # noqa: RUF022
    # Version
    "__version__",
    # Core
    "Belgie",
    "BelgieClient",
    "BelgieSettings",
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
