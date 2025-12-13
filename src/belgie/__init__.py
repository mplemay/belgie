"""Belgie - Modern authentication and analytics for FastAPI."""

__version__ = "0.1.0"

__all__: list[str] = ["__version__"]

try:
    from belgie.auth import (
        AccountProtocol,
        AlchemyAdapter,
        Auth,
        AuthenticationError,
        AuthorizationError,
        AuthSettings,
        BelgieError,
        ConfigurationError,
        CookieSettings,
        GoogleOAuthProvider,
        GoogleProviderSettings,
        GoogleUserInfo,
        HookContext,
        HookEvent,
        HookRunner,
        Hooks,
        InvalidStateError,
        OAuthError,
        OAuthStateProtocol,
        SessionExpiredError,
        SessionManager,
        SessionProtocol,
        SessionSettings,
        URLSettings,
        UserProtocol,
        generate_session_id,
        generate_state_token,
        parse_scopes,
        validate_scopes,
    )
except ImportError:
    pass
else:
    __all__.extend(
        [
            "AccountProtocol",
            "AlchemyAdapter",
            "Auth",
            "AuthSettings",
            "AuthenticationError",
            "AuthorizationError",
            "BelgieError",
            "ConfigurationError",
            "CookieSettings",
            "GoogleOAuthProvider",
            "GoogleProviderSettings",
            "GoogleUserInfo",
            "HookContext",
            "HookEvent",
            "HookRunner",
            "Hooks",
            "InvalidStateError",
            "OAuthError",
            "OAuthStateProtocol",
            "SessionExpiredError",
            "SessionManager",
            "SessionProtocol",
            "SessionSettings",
            "URLSettings",
            "UserProtocol",
            "generate_session_id",
            "generate_state_token",
            "parse_scopes",
            "validate_scopes",
        ],
    )

try:
    from belgie.trace import (
        Trace,
        TraceAdapterProtocol,
        TraceClient,
        TraceError,
        TraceSettings,
    )
except ImportError:
    pass
else:
    __all__.extend(
        [
            "Trace",
            "TraceAdapterProtocol",
            "TraceClient",
            "TraceError",
            "TraceSettings",
        ],
    )
