from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from belgie_core.core.exceptions import InvalidStateError, OAuthError
from belgie_core.core.plugin import Plugin
from belgie_core.utils.crypto import generate_state_token
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient


class GoogleOAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_GOOGLE_",
        env_file=".env",
        extra="ignore",
    )

    client_id: str
    client_secret: SecretStr
    redirect_uri: str
    scopes: list[str] = Field(default=["openid", "email", "profile"])
    access_type: str = Field(default="offline")
    prompt: str = Field(default="consent")

    @field_validator("client_id", "redirect_uri")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:  # noqa: ANN001
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        return value.strip()

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret or not secret.strip():
            msg = "client_secret must be a non-empty string"
            raise ValueError(msg)
        return SecretStr(secret.strip())


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


@dataclass(slots=True, kw_only=True)
class GoogleOAuthClient:
    plugin: GoogleOAuthPlugin
    client: BelgieClient

    async def signin_url(self, *, return_to: str | None = None) -> str:
        state = generate_state_token()
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        redirect_url = self.plugin.normalize_return_to(return_to)
        await self.client.adapter.create_oauth_state(
            self.client.db,
            state=state,
            expires_at=expires_at.replace(tzinfo=None),
            redirect_url=redirect_url,
        )
        return self.plugin.generate_authorization_url(state)


class GoogleOAuthPlugin(Plugin):
    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def __init__(self, settings: GoogleOAuthSettings) -> None:
        self.settings = settings
        self._resolve_client = None
        self._base_url_origin: tuple[str, str] | None = None

    @property
    def provider_id(self) -> Literal["google"]:
        return "google"

    def bind(self, belgie: Belgie) -> None:
        async def resolve_client(client: BelgieClient = Depends(belgie)) -> GoogleOAuthClient:  # noqa: B008
            return GoogleOAuthClient(plugin=self, client=client)

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)
        parsed_base_url = urlparse(belgie.settings.base_url)
        self._base_url_origin = (parsed_base_url.scheme.lower(), parsed_base_url.netloc.lower())

    def normalize_return_to(self, return_to: str | None) -> str | None:
        if not return_to:
            return None

        parsed = urlparse(return_to)

        if not parsed.scheme and not parsed.netloc:
            if return_to.startswith("/") and not return_to.startswith("//"):
                return return_to
            return None

        if self._base_url_origin is None:
            msg = "GoogleOAuthPlugin must be registered via Belgie.add_plugin before dependency injection"
            raise RuntimeError(msg)

        if (parsed.scheme.lower(), parsed.netloc.lower()) != self._base_url_origin:
            return None

        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))

    async def __call__(self, *args: object, **kwargs: object) -> GoogleOAuthClient:
        if self._resolve_client is None:
            msg = "GoogleOAuthPlugin must be registered via Belgie.add_plugin before dependency injection"
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    def generate_authorization_url(self, state: str) -> str:
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
            error_detail = ""
            try:
                error_data = e.response.json()
                if isinstance(error_data, dict) and "error" in error_data:
                    error_detail = f" ({error_data['error']})"
            except (ValueError, KeyError, TypeError):
                pass
            msg = f"oauth token exchange failed: {e.response.status_code}{error_detail}"
            raise OAuthError(msg) from e
        except httpx.RequestError as e:
            msg = "oauth token exchange request failed"
            raise OAuthError(msg) from e

    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
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
            error_detail = ""
            try:
                error_data = e.response.json()
                if isinstance(error_data, dict) and "error" in error_data:
                    error_detail = f" ({error_data['error']})"
            except (ValueError, KeyError, TypeError):
                pass
            msg = f"failed to fetch user info: {e.response.status_code}{error_detail}"
            raise OAuthError(msg) from e
        except httpx.RequestError as e:
            msg = "user info request failed"
            raise OAuthError(msg) from e

    def router(self, belgie: Belgie) -> APIRouter:
        router = APIRouter(prefix=f"/provider/{self.provider_id}", tags=["auth", "oauth"])

        async def callback(
            code: str,
            state: str,
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> RedirectResponse:
            oauth_state = await client.adapter.get_oauth_state(client.db, state)
            if not oauth_state:
                msg = "Invalid OAuth state"
                raise InvalidStateError(msg)
            await client.adapter.delete_oauth_state(client.db, state)

            tokens = await self.exchange_code_for_tokens(code)
            user_info = await self.get_user_info(tokens["access_token"])

            user, session = await client.sign_up(
                user_info.email,
                request=request,
                name=user_info.name,
                image=user_info.picture,
                email_verified=user_info.verified_email,
            )

            await client.upsert_oauth_account(
                user_id=user.id,
                provider=self.provider_id,
                provider_account_id=user_info.id,
                access_token=tokens["access_token"],
                refresh_token=tokens.get("refresh_token"),
                expires_at=tokens.get("expires_at"),
                scope=tokens.get("scope"),
                token_type=tokens.get("token_type"),
                id_token=tokens.get("id_token"),
            )

            response = RedirectResponse(
                url=oauth_state.redirect_url or belgie.settings.urls.signin_redirect,
                status_code=302,
            )
            return client.create_session_cookie(session, response)

        router.add_api_route("/callback", callback, methods=["GET"])

        return router

    def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return APIRouter()
