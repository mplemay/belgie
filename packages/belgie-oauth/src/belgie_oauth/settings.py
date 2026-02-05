from __future__ import annotations

from functools import cached_property
from typing import Literal
from urllib.parse import urlparse, urlunparse

from pydantic import AnyHttpUrl, AnyUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BELGIE_OAUTH_")

    base_url: AnyHttpUrl | None = None
    route_prefix: str = "/oauth"
    login_url: str | None = None
    consent_url: str | None = None
    post_login_url: str | None = None
    select_account_url: str | None = None
    end_session_url: str | None = None

    client_id: str = "belgie_client"
    client_secret: SecretStr | None = None
    redirect_uris: list[AnyUrl] = Field(..., min_length=1)
    default_scope: str = "user"
    scopes: list[str] | None = None
    grant_types: list[str] | None = None

    allow_dynamic_client_registration: bool = False
    allow_unauthenticated_client_registration: bool = False
    client_registration_allowed_scopes: list[str] | None = None
    client_registration_default_scopes: list[str] | None = None

    authorization_code_ttl_seconds: int = 300
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 2592000
    state_ttl_seconds: int = 600
    code_challenge_method: Literal["S256"] = "S256"

    @cached_property
    def issuer_url(self) -> AnyHttpUrl | None:
        if self.base_url is None:
            return None

        parsed = urlparse(str(self.base_url))
        base_path = parsed.path.rstrip("/")
        prefix = self.route_prefix.strip("/")
        auth_path = "auth"
        full_path = f"{base_path}/{auth_path}/{prefix}" if prefix else f"{base_path}/{auth_path}"
        return AnyHttpUrl(urlunparse(parsed._replace(path=full_path, query="", fragment="")))
