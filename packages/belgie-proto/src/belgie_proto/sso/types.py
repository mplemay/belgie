from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCClaimMapping:
    subject: str = "sub"
    email: str = "email"
    email_verified: str = "email_verified"
    name: str = "name"
    image: str = "picture"
    extra_fields: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCProviderConfig:
    client_id: str
    client_secret: str
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    discovery_endpoint: str | None = None
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    token_endpoint_auth_method: str = "client_secret_basic"  # noqa: S105
    claim_mapping: OIDCClaimMapping = field(default_factory=OIDCClaimMapping)
    pkce: bool = True
    override_user_info: bool = False
