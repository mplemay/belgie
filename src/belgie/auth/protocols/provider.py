from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from fastapi import APIRouter

    from belgie.auth.protocols.adapter import AdapterProtocol


class OAuthProviderProtocol[S: BaseSettings](Protocol):
    """Protocol that all OAuth providers must implement.

    Each provider is self-contained and manages its own routes.
    Providers create FastAPI routers with OAuth endpoints and handle
    the complete OAuth flow internally.
    """

    def __init__(self, settings: S) -> None:
        """Initialize provider with settings.

        Args:
            settings: Provider-specific settings (must extend BaseSettings)
        """
        ...

    @property
    def provider_id(self) -> str:
        """Unique identifier for this provider.

        Concrete implementations must return Literal types for type safety.
        Example: Literal["google"], Literal["github"]

        Returns:
            Provider identifier string
        """
        ...

    def get_router(self, adapter: AdapterProtocol) -> APIRouter:
        """Create and return FastAPI router with OAuth endpoints.

        The router should include:
        - GET /{provider_id}/signin - Initiates OAuth flow
        - GET /{provider_id}/callback - Handles OAuth callback

        Args:
            adapter: Database adapter for persistence operations

        Returns:
            FastAPI router with OAuth endpoints configured

        Implementation Notes:
            The adapter provides database access via dependency injection:
            - db = Depends(adapter.get_db)

            The provider has complete control over:
            - OAuth flow implementation
            - User data mapping
            - Session management (duration, cookie configuration from provider settings)
            - Error handling
            - Redirect URLs

            Provider settings should include:
            - OAuth credentials (client_id, client_secret, redirect_uri, scopes)
            - Cookie configuration (httponly, secure, samesite, domain, cookie_name)
            - Session configuration (max_age)
            - Redirect URLs (signin_redirect, signout_redirect)

            Implementation style:
            - Use closures that capture self for route handlers
            - Register routes with router.add_api_route()
            - Use walrus operator where appropriate
            - Use dict.get() for safe dictionary access
        """
        ...
