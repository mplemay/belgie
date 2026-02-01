from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from proto import AdapterProtocol, DBConnection
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import SettingsConfigDict

from belgie.auth.core.exceptions import InvalidStateError, OAuthError
from belgie.auth.core.hooks import HookContext, HookRunner
from belgie.auth.core.settings import CookieSettings, ProviderSettings
from belgie.auth.utils.crypto import generate_state_token


class GoogleProviderSettings(ProviderSettings):
    """Google OAuth provider settings loaded from environment.

    Contains only Google-specific OAuth configuration.
    Session and redirect settings are passed via get_router() parameters.
    """

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_GOOGLE_",
        env_file=".env",
        extra="ignore",
    )

    scopes: list[str] = Field(default=["openid", "email", "profile"])
    access_type: str = Field(default="offline")
    prompt: str = Field(default="consent")

    def __call__(self) -> "GoogleOAuthProvider":
        """Create and return Google OAuth provider instance.

        Returns:
            GoogleOAuthProvider configured with these settings
        """
        return GoogleOAuthProvider(settings=self)


class GoogleUserInfo(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    id: str
    email: str
    verified_email: bool
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    locale: str | None = None


class GoogleOAuthProvider:
    """Google OAuth provider - self-contained implementation."""

    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def __init__(self, settings: GoogleProviderSettings) -> None:
        self.settings = settings

    @property
    def provider_id(self) -> Literal["google"]:
        return "google"

    def generate_authorization_url(self, state: str) -> str:
        """Generate Google OAuth authorization URL."""
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.settings.scopes),
            "state": state,
            "access_type": self.settings.access_type,
            "prompt": self.settings.prompt,
        }
        parsed = urlparse(self.AUTHORIZATION_URL)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                "",
                urlencode(params),
                "",
            ),
        )

    async def exchange_code_for_tokens(self, code: str) -> dict:
        """Exchange authorization code for access and refresh tokens."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret.get_secret_value(),
                        "code": code,
                        "redirect_uri": self.settings.redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                response.raise_for_status()
                tokens = response.json()

                if "access_token" not in tokens:
                    msg = "missing required field in token response: access_token"
                    raise OAuthError(msg)

                # Calculate expires_at if expires_in is present
                return {
                    "access_token": tokens["access_token"],
                    "token_type": tokens.get("token_type"),
                    "refresh_token": tokens.get("refresh_token"),
                    "scope": tokens.get("scope"),
                    "id_token": tokens.get("id_token"),
                    "expires_at": (
                        datetime.now(UTC) + timedelta(seconds=tokens["expires_in"]) if "expires_in" in tokens else None
                    ),
                }
        except httpx.HTTPStatusError as e:
            # Safely extract error code from response without exposing sensitive details
            error_detail = ""
            try:
                error_data = e.response.json()
                if isinstance(error_data, dict) and "error" in error_data:
                    error_detail = f" ({error_data['error']})"
            except (ValueError, KeyError, TypeError):
                # Ignore JSON parsing errors or missing fields
                pass
            msg = f"oauth token exchange failed: {e.response.status_code}{error_detail}"
            raise OAuthError(msg) from e
        except httpx.RequestError as e:
            msg = "oauth token exchange request failed"
            raise OAuthError(msg) from e

    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
        """Fetch user information from Google using access token."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.USER_INFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                user_data = response.json()
                return GoogleUserInfo(**user_data)
        except httpx.HTTPStatusError as e:
            # Safely extract error code from response without exposing sensitive details
            error_detail = ""
            try:
                error_data = e.response.json()
                if isinstance(error_data, dict) and "error" in error_data:
                    error_detail = f" ({error_data['error']})"
            except (ValueError, KeyError, TypeError):
                # Ignore JSON parsing errors or missing fields
                pass
            msg = f"failed to fetch user info: {e.response.status_code}{error_detail}"
            raise OAuthError(msg) from e
        except httpx.RequestError as e:
            msg = "user info request failed"
            raise OAuthError(msg) from e

    def get_router(  # noqa: PLR0913
        self,
        adapter: AdapterProtocol,
        cookie_settings: CookieSettings,
        session_max_age: int,
        signin_redirect: str,
        signout_redirect: str,  # noqa: ARG002
        hook_runner: HookRunner,
        db_dependency: Callable[[], DBConnection | AsyncGenerator[DBConnection, None]],
    ) -> APIRouter:
        """Create router with Google OAuth endpoints."""
        router = APIRouter(prefix=f"/{self.provider_id}", tags=["auth", "oauth"])

        async def signin(db: DBConnection = Depends(db_dependency)) -> RedirectResponse:  # noqa: B008
            """Initiate Google OAuth flow."""
            # Generate and store state token with expiration
            state = generate_state_token()
            expires_at = datetime.now(UTC) + timedelta(minutes=10)
            await adapter.create_oauth_state(
                db,
                state=state,
                expires_at=expires_at.replace(tzinfo=None),
            )

            # Generate authorization URL using helper method
            auth_url = self.generate_authorization_url(state)
            return RedirectResponse(url=auth_url, status_code=302)

        async def callback(code: str, state: str, db: DBConnection = Depends(db_dependency)) -> RedirectResponse:  # noqa: B008
            """Handle Google OAuth callback."""
            # Validate and delete state token (use walrus operator)
            if not await adapter.get_oauth_state(db, state):
                msg = "Invalid OAuth state"
                raise InvalidStateError(msg)
            await adapter.delete_oauth_state(db, state)

            # Exchange code for tokens using helper method
            tokens = await self.exchange_code_for_tokens(code)

            # Fetch user info using helper method
            user_info = await self.get_user_info(tokens["access_token"])

            created = False
            # Get or create user (use walrus operator)
            if not (user := await adapter.get_user_by_email(db, user_info.email)):
                user = await adapter.create_user(
                    db,
                    email=user_info.email,
                    email_verified=user_info.verified_email,
                    name=user_info.name,
                    image=user_info.picture,
                )
                created = True

            # Create or update OAuth account (use dict.get for optional tokens)
            if await adapter.get_account_by_user_and_provider(
                db,
                user.id,
                self.provider_id,
            ):
                await adapter.update_account(
                    db,
                    user_id=user.id,
                    provider=self.provider_id,
                    access_token=tokens["access_token"],
                    refresh_token=tokens.get("refresh_token"),
                    expires_at=tokens.get("expires_at"),
                    scope=tokens.get("scope"),
                )
            else:
                await adapter.create_account(
                    db,
                    user_id=user.id,
                    provider=self.provider_id,
                    provider_account_id=user_info.id,
                    access_token=tokens["access_token"],
                    refresh_token=tokens.get("refresh_token"),
                    expires_at=tokens.get("expires_at"),
                    scope=tokens.get("scope"),
                )

            # Hooks: signup (only on create)
            if created:
                async with hook_runner.dispatch("on_signup", HookContext(user=user, db=db)):
                    pass

            # Create session with proper expiration
            expires_at = datetime.now(UTC) + timedelta(seconds=session_max_age)
            session = await adapter.create_session(
                db,
                user_id=user.id,
                expires_at=expires_at.replace(tzinfo=None),
            )

            async with hook_runner.dispatch("on_signin", HookContext(user=user, db=db)):
                pass

            # Set session cookie using centralized cookie settings
            response = RedirectResponse(url=signin_redirect, status_code=302)
            response.set_cookie(
                key=cookie_settings.name,
                value=str(session.id),
                max_age=session_max_age,
                httponly=cookie_settings.http_only,
                secure=cookie_settings.secure,
                samesite=cookie_settings.same_site,
                domain=cookie_settings.domain,
            )
            return response

        # Register routes
        router.add_api_route("/signin", signin, methods=["GET"])
        router.add_api_route("/callback", callback, methods=["GET"])

        return router
