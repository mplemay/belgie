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
    DatabaseProtocol,
    DBConnection,
    InvalidStateError,
    OAuthError,
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
    from belgie_alchemy.core.adapter import BelgieAdapter

__version__ = "0.1.0"

_ALCHEMY_IMPORT_ERROR = "BelgieAdapter requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"


def __getattr__(name: str) -> object:
    if name != "BelgieAdapter":
        msg = f"module 'belgie' has no attribute {name!r}"
        raise AttributeError(msg)

    try:
        module = import_module("belgie_alchemy.core.adapter")
    except ModuleNotFoundError as exc:
        raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

    return module.BelgieAdapter


__all__ = [  # noqa: RUF022
    # Version
    "__version__",
    # Core
    "Belgie",
    "BelgieClient",
    "BelgieSettings",
    # Adapters
    "BelgieAdapter",
    "DBConnection",
    "DatabaseProtocol",
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
