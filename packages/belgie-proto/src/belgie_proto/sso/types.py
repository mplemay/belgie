from __future__ import annotations

from dataclasses import dataclass, field

type OIDCExtraClaimMapping = dict[str, str]
type SAMLExtraClaimMapping = dict[str, str]
type OIDCClaimMappingValue = str | OIDCExtraClaimMapping
type SAMLClaimMappingValue = str | SAMLExtraClaimMapping
type OIDCConfigValue = str | bool | list[str] | dict[str, OIDCClaimMappingValue]
type SAMLConfigValue = str | bool | list[str] | dict[str, SAMLClaimMappingValue]


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCClaimMapping:
    subject: str = "sub"
    email: str = "email"
    email_verified: str = "email_verified"
    name: str = "name"
    image: str = "picture"
    extra_fields: OIDCExtraClaimMapping = field(default_factory=dict)


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCProviderConfig:
    issuer: str
    client_id: str
    client_secret: str
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    discovery_endpoint: str | None = None
    jwks_uri: str | None = None
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    token_endpoint_auth_method: str = "client_secret_basic"  # noqa: S105
    use_pkce: bool = True
    override_user_info_on_sign_in: bool = False
    claim_mapping: OIDCClaimMapping = field(default_factory=OIDCClaimMapping)


@dataclass(slots=True, kw_only=True, frozen=True)
class SAMLClaimMapping:
    subject: str = "name_id"
    email: str = "email"
    email_verified: str = "email_verified"
    name: str = "name"
    first_name: str = "first_name"
    last_name: str = "last_name"
    groups: str = "groups"
    extra_fields: SAMLExtraClaimMapping = field(default_factory=dict)


@dataclass(slots=True, kw_only=True, frozen=True)
class SAMLProviderConfig:
    entity_id: str
    sso_url: str
    x509_certificate: str
    slo_url: str | None = None
    audience: str | None = None
    idp_metadata_xml: str | None = None
    name_id_format: str | None = None
    binding: str = "redirect"
    allow_idp_initiated: bool = False
    want_assertions_signed: bool = True
    sign_authn_request: bool = True
    signature_algorithm: str = "rsa-sha256"
    digest_algorithm: str = "sha256"
    private_key: str | None = None
    private_key_passphrase: str | None = None
    signing_certificate: str | None = None
    decryption_private_key: str | None = None
    decryption_private_key_passphrase: str | None = None
    claim_mapping: SAMLClaimMapping = field(default_factory=SAMLClaimMapping)
