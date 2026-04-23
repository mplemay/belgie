import re
from dataclasses import asdict
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlparse, urlunparse

from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig, SAMLClaimMapping, SAMLProviderConfig

_DOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_MASKED_CLIENT_ID_VISIBLE_CHARS = 3
_MASKED_CLIENT_ID_SHORT_LIMIT = _MASKED_CLIENT_ID_VISIBLE_CHARS * 2

if TYPE_CHECKING:
    from belgie_proto.sso import SSODomainProtocol


def normalize_issuer(issuer: str) -> str:
    value = issuer.strip().rstrip("/")
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        msg = "issuer must be an absolute URL"
        raise ValueError(msg)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))


def normalize_provider_id(provider_id: str) -> str:
    value = provider_id.strip().lower()
    if not _PROVIDER_ID_PATTERN.fullmatch(value):
        msg = "provider_id must contain only lowercase letters, digits, '_' or '-'"
        raise ValueError(msg)
    return value


def normalize_domain(domain: str) -> str:
    value = domain.strip().lower().rstrip(".")
    if not _DOMAIN_PATTERN.fullmatch(value) or ".." in value or "@" in value or "/" in value:
        msg = "domain must be a valid hostname"
        raise ValueError(msg)
    return value


def extract_email_domain(email: str) -> str | None:
    local_part, separator, domain = email.strip().partition("@")
    if not local_part or separator != "@" or not domain:
        return None
    try:
        return normalize_domain(domain)
    except ValueError:
        return None


def normalize_return_to(return_to: str | None, *, base_url: str) -> str | None:
    return normalize_redirect_target(return_to, base_url=base_url)


def normalize_redirect_target(
    target: str | None,
    *,
    base_url: str,
    trusted_origins: tuple[str, ...] = (),
) -> str | None:
    if not target:
        return None

    parsed_base_url = urlparse(base_url)
    allowed_origins = {
        (parsed_base_url.scheme.lower(), parsed_base_url.netloc.lower()),
        *(_normalize_origin(origin) for origin in trusted_origins),
    }
    parsed = urlparse(target)

    if not parsed.scheme and not parsed.netloc:
        if target.startswith("/") and not target.startswith("//"):
            return target
        return None

    if (parsed.scheme.lower(), parsed.netloc.lower()) not in allowed_origins:
        return None

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def build_provider_callback_url(base_url: str, *, provider_id: str) -> str:
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    callback_path = f"/auth/provider/sso/callback/{provider_id}"
    full_path = f"{base_path}{callback_path}" if base_path else callback_path
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))


def build_shared_callback_url(base_url: str, *, redirect_uri: str | None = None) -> str:
    if redirect_uri:
        return redirect_uri

    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    callback_path = "/auth/provider/sso/callback"
    full_path = f"{base_path}{callback_path}" if base_path else callback_path
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))


def build_authorization_url(  # noqa: PLR0913
    *,
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    login_hint: str | None = None,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint

    parsed = urlparse(authorization_endpoint)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(params), ""))


def serialize_oidc_config(config: OIDCProviderConfig) -> dict[str, str | list[str] | dict[str, str]]:
    payload = asdict(config)
    payload["scopes"] = list(config.scopes)
    return payload


def deserialize_oidc_config(payload: dict[str, str | bool | list[str] | dict[str, str]]) -> OIDCProviderConfig:
    raw_claim_mapping = payload.get("claim_mapping", {})
    claim_mapping = OIDCClaimMapping(
        subject=str(raw_claim_mapping.get("subject", "sub")),
        email=str(raw_claim_mapping.get("email", "email")),
        email_verified=str(raw_claim_mapping.get("email_verified", "email_verified")),
        name=str(raw_claim_mapping.get("name", "name")),
        image=str(raw_claim_mapping.get("image", "picture")),
        extra_fields={
            str(key): str(value)
            for key, value in raw_claim_mapping.get("extra_fields", {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if isinstance(raw_claim_mapping.get("extra_fields"), dict)
        else {},
    )
    raw_scopes = payload.get("scopes", ["openid", "email", "profile"])
    scopes = tuple(scope for scope in raw_scopes if isinstance(scope, str))

    return OIDCProviderConfig(
        issuer=str(payload["issuer"]),
        client_id=str(payload["client_id"]),
        client_secret=str(payload["client_secret"]),
        authorization_endpoint=str(payload["authorization_endpoint"])
        if payload.get("authorization_endpoint")
        else None,
        token_endpoint=str(payload["token_endpoint"]) if payload.get("token_endpoint") else None,
        userinfo_endpoint=str(payload["userinfo_endpoint"]) if payload.get("userinfo_endpoint") else None,
        discovery_endpoint=str(payload["discovery_endpoint"]) if payload.get("discovery_endpoint") else None,
        jwks_uri=str(payload["jwks_uri"]) if payload.get("jwks_uri") is not None else None,
        scopes=scopes,
        token_endpoint_auth_method=str(payload.get("token_endpoint_auth_method", "client_secret_basic")),
        use_pkce=bool(payload.get("use_pkce", True)),
        override_user_info_on_sign_in=bool(payload.get("override_user_info_on_sign_in", False)),
        claim_mapping=claim_mapping,
    )


def serialize_saml_config(config: SAMLProviderConfig) -> dict[str, str | bool | list[str] | dict[str, str]]:
    return asdict(config)


def deserialize_saml_config(payload: dict[str, str | bool | list[str] | dict[str, str]]) -> SAMLProviderConfig:
    raw_claim_mapping = payload.get("claim_mapping", {})
    claim_mapping = SAMLClaimMapping(
        subject=str(raw_claim_mapping.get("subject", "name_id")),
        email=str(raw_claim_mapping.get("email", "email")),
        email_verified=str(raw_claim_mapping.get("email_verified", "email_verified")),
        name=str(raw_claim_mapping.get("name", "name")),
        groups=str(raw_claim_mapping.get("groups", "groups")),
    )
    return SAMLProviderConfig(
        entity_id=str(payload["entity_id"]),
        sso_url=str(payload["sso_url"]),
        x509_certificate=str(payload["x509_certificate"]),
        slo_url=str(payload["slo_url"]) if payload.get("slo_url") else None,
        name_id_format=str(payload["name_id_format"]) if payload.get("name_id_format") else None,
        binding=str(payload.get("binding", "redirect")),
        allow_idp_initiated=bool(payload.get("allow_idp_initiated", False)),
        want_assertions_signed=bool(payload.get("want_assertions_signed", True)),
        sign_authn_request=bool(payload.get("sign_authn_request", True)),
        signature_algorithm=str(payload.get("signature_algorithm", "rsa-sha256")),
        digest_algorithm=str(payload.get("digest_algorithm", "sha256")),
        claim_mapping=claim_mapping,
    )


def as_account_provider(provider_id: str) -> str:
    return f"sso:{provider_id}"


def parse_bool_claim(*, value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes"}


def build_domain_verification_record_name(
    *,
    domain: str,
    provider_id: str,
    token_prefix: str,
) -> str:
    normalized_prefix = token_prefix.strip().strip("_")
    return f"_{normalized_prefix}-{normalize_provider_id(provider_id)}.{normalize_domain(domain)}"


def build_domain_verification_record_value(
    *,
    provider_id: str,
    token_prefix: str,
    verification_token: str,
) -> str:
    normalized_prefix = token_prefix.strip().strip("_")
    normalized_provider_id = normalize_provider_id(provider_id)
    return f"_{normalized_prefix}-{normalized_provider_id}={verification_token}"


def choose_best_verified_domain_match[DomainT: SSODomainProtocol](
    *,
    domain: str,
    domains: list[DomainT],
) -> DomainT | None:
    exact_matches = [item for item in domains if item.domain == domain]
    if len(exact_matches) > 1:
        msg = f"multiple verified providers match domain '{domain}'"
        raise ValueError(msg)
    if exact_matches:
        return exact_matches[0]

    suffix_matches = [item for item in domains if domain.endswith(f".{item.domain}")]
    if not suffix_matches:
        return None

    max_length = max(len(item.domain) for item in suffix_matches)
    best_matches = [item for item in suffix_matches if len(item.domain) == max_length]
    if len(best_matches) > 1:
        msg = f"multiple verified providers match domain '{domain}'"
        raise ValueError(msg)
    return best_matches[0]


def mask_client_id(client_id: str | None) -> str | None:
    if client_id is None:
        return None
    if len(client_id) <= _MASKED_CLIENT_ID_SHORT_LIMIT:
        return "*" * len(client_id)
    return f"{client_id[:_MASKED_CLIENT_ID_VISIBLE_CHARS]}***{client_id[-_MASKED_CLIENT_ID_VISIBLE_CHARS:]}"


def _normalize_origin(origin: str) -> tuple[str, str]:
    parsed = urlparse(origin)
    return parsed.scheme.lower(), parsed.netloc.lower()
