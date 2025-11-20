from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict

from brugge.auth.core.exceptions import OAuthError


@dataclass
class GoogleTokenResponse:
    access_token: str
    expires_in: int
    token_type: str
    scope: str
    refresh_token: str | None = None
    id_token: str | None = None


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
    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str],
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes

    def generate_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.AUTHORIZATION_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.TOKEN_URL, data=data)
                response.raise_for_status()
                token_data = response.json()

                expires_at = None
                if expires_in := token_data.get("expires_in"):
                    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

                return {
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_at": expires_at,
                    "token_type": token_data.get("token_type"),
                    "scope": token_data.get("scope"),
                    "id_token": token_data.get("id_token"),
                }
        except httpx.HTTPStatusError as e:
            error_message = f"oauth token exchange failed: {e.response.status_code}"
            raise OAuthError(error_message) from e
        except httpx.RequestError as e:
            error_message = f"oauth token exchange request failed: {e}"
            raise OAuthError(error_message) from e
        except KeyError as e:
            error_message = f"missing required field in token response: {e}"
            raise OAuthError(error_message) from e

    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.USER_INFO_URL, headers=headers)
                response.raise_for_status()
                user_data = response.json()
                return GoogleUserInfo(**user_data)
        except httpx.HTTPStatusError as e:
            error_message = f"failed to fetch user info: {e.response.status_code}"
            raise OAuthError(error_message) from e
        except httpx.RequestError as e:
            error_message = f"user info request failed: {e}"
            raise OAuthError(error_message) from e
