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

    client_id: str = "belgie_client"
    client_secret: SecretStr | None = None
    redirect_uris: list[AnyUrl] = Field(..., min_length=1)
    default_scope: str = "user"

    authorization_code_ttl_seconds: int = 300
    access_token_ttl_seconds: int = 3600
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
