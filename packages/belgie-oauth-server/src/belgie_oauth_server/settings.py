from __future__ import annotations

from functools import cached_property
from typing import Literal
from urllib.parse import urlparse, urlunparse

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OAuthResource(BaseModel):
    prefix: str
    scopes: list[str] | None = None

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "prefix must be a non-empty path"
            raise ValueError(msg)
        if not normalized.startswith("/"):
            msg = "prefix must start with '/'"
            raise ValueError(msg)
        return normalized

    def resolve_url(self, base_url: str | AnyHttpUrl) -> AnyHttpUrl:
        parsed = urlparse(str(base_url))
        base_path = parsed.path.rstrip("/")
        prefix_path = self.prefix.strip("/")
        if not prefix_path:
            full_path = base_path or "/"
        elif base_path:
            full_path = f"{base_path}/{prefix_path}"
        else:
            full_path = f"/{prefix_path}"
        return AnyHttpUrl(urlunparse(parsed._replace(path=full_path, query="", fragment="")))


class OAuthServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_OAUTH_",
        env_file=".env",
        extra="ignore",
    )

    base_url: AnyHttpUrl | None = None
    prefix: str = "/oauth"
    login_url: str | None = None

    client_id: str = "belgie_client"
    client_secret: SecretStr | None = None
    redirect_uris: list[AnyUrl] = Field(..., min_length=1)
    default_scope: str = "user"

    authorization_code_ttl_seconds: int = 300
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 2592000
    id_token_ttl_seconds: int = 36000
    state_ttl_seconds: int = 600
    code_challenge_method: Literal["S256"] = "S256"
    enable_end_session: bool = False
    allow_dynamic_client_registration: bool = False
    allow_unauthenticated_client_registration: bool = False
    resources: list[OAuthResource] | None = Field(default=None, min_length=1, max_length=1)
    include_root_resource_metadata_fallback: bool = True
    include_root_oauth_metadata_fallback: bool = True
    include_root_openid_metadata_fallback: bool = True

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_settings(cls, values: object) -> object:
        if isinstance(values, dict):
            if "route_prefix" in values:
                msg = "`route_prefix` has been removed; use `prefix` instead"
                raise ValueError(msg)
            if "resource_server_url" in values:
                msg = "`resource_server_url` has been removed; use `resources=[OAuthResource(...)]` instead"
                raise ValueError(msg)
            if "resource_scopes" in values:
                msg = "`resource_scopes` has been removed; use `resources=[OAuthResource(scopes=[...])]` instead"
                raise ValueError(msg)
        return values

    @cached_property
    def issuer_url(self) -> AnyHttpUrl | None:
        if self.base_url is None:
            return None

        parsed = urlparse(str(self.base_url))
        base_path = parsed.path.rstrip("/")
        prefix = self.prefix.strip("/")
        auth_path = "auth"
        full_path = f"{base_path}/{auth_path}/{prefix}" if prefix else f"{base_path}/{auth_path}"
        return AnyHttpUrl(urlunparse(parsed._replace(path=full_path, query="", fragment="")))

    def resolve_resource(
        self,
        fallback_base_url: str | AnyHttpUrl | None = None,
    ) -> tuple[AnyHttpUrl, list[str] | None] | None:
        if self.resources is None:
            return None

        base_url = self.base_url if self.base_url is not None else fallback_base_url
        if base_url is None:
            msg = "base_url is required to resolve OAuth resources"
            raise ValueError(msg)

        resource = self.resources[0]
        return resource.resolve_url(base_url), resource.scopes
