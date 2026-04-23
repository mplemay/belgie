import re
from dataclasses import asdict
from hashlib import sha256
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig, SAMLClaimMapping, SAMLProviderConfig

_DOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_HTTP_SCHEMES = {"http", "https"}
_MASKED_CLIENT_ID_VISIBLE_CHARS = 4

if TYPE_CHECKING:
    from belgie_proto.sso import SSODomainProtocol


def normalize_issuer(issuer: str) -> str:
    value = issuer.strip().rstrip("/")
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        msg = "issuer must be an absolute URL"
        raise ValueError(msg)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))


def normalize_http_url(url: str, *, field_name: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc or parsed.scheme.lower() not in _HTTP_SCHEMES:
        msg = f"{field_name} must be an absolute http(s) URL"
        raise ValueError(msg)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.params, parsed.query, ""))


def resolve_http_url(url: str, *, base_url: str, field_name: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return normalize_http_url(value, field_name=field_name)
    joined = (
        urljoin(f"{normalize_issuer(base_url)}/", value.lstrip("/"))
        if not value.startswith("/")
        else urljoin(
            f"{normalize_issuer(base_url)}/",
            value,
        )
    )
    return normalize_http_url(joined, field_name=field_name)


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
            if _is_callback_path(target):
                return None
            return target
        return None

    if (parsed.scheme.lower(), parsed.netloc.lower()) not in allowed_origins:
        return None

    normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))
    return None if _is_callback_path(parsed.path) else normalized


def build_provider_callback_url(base_url: str, *, provider_id: str) -> str:
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    callback_path = f"/auth/provider/sso/callback/{provider_id}"
    full_path = f"{base_path}{callback_path}" if base_path else callback_path
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))


def build_shared_callback_url(base_url: str, *, redirect_uri: str | None = None) -> str:
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        if parsed.scheme or parsed.netloc:
            return normalize_http_url(redirect_uri, field_name="redirect_uri")

        normalized_path = redirect_uri if redirect_uri.startswith("/") else f"/{redirect_uri}"
        parsed_base = urlparse(base_url)
        base_path = parsed_base.path.rstrip("/")
        full_path = f"{base_path}{normalized_path}" if base_path else normalized_path
        return urlunparse(parsed_base._replace(path=full_path, query="", fragment=""))

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


def deserialize_oidc_config(
    payload: dict[str, str | bool | list[str] | dict[str, str | dict[str, str]]],
) -> OIDCProviderConfig:
    raw_claim_mapping_value = payload.get("claim_mapping", {})
    raw_claim_mapping = raw_claim_mapping_value if isinstance(raw_claim_mapping_value, dict) else {}
    raw_extra_fields = raw_claim_mapping.get("extra_fields", {})
    claim_mapping = OIDCClaimMapping(
        subject=str(raw_claim_mapping.get("subject", "sub")),
        email=str(raw_claim_mapping.get("email", "email")),
        email_verified=str(raw_claim_mapping.get("email_verified", "email_verified")),
        name=str(raw_claim_mapping.get("name", "name")),
        image=str(raw_claim_mapping.get("image", "picture")),
        extra_fields={
            str(key): str(value)
            for key, value in raw_extra_fields.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if isinstance(raw_extra_fields, dict)
        else {},
    )
    raw_scopes_value = payload.get("scopes", ["openid", "email", "profile"])
    raw_scopes = raw_scopes_value if isinstance(raw_scopes_value, list) else ["openid", "email", "profile"]
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


def deserialize_saml_config(
    payload: dict[str, str | bool | list[str] | dict[str, str | dict[str, str]]],
) -> SAMLProviderConfig:
    raw_claim_mapping_value = payload.get("claim_mapping", {})
    raw_claim_mapping = raw_claim_mapping_value if isinstance(raw_claim_mapping_value, dict) else {}
    raw_extra_fields = raw_claim_mapping.get("extra_fields", {})
    claim_mapping = SAMLClaimMapping(
        subject=str(raw_claim_mapping.get("subject", "name_id")),
        email=str(raw_claim_mapping.get("email", "email")),
        email_verified=str(raw_claim_mapping.get("email_verified", "email_verified")),
        name=str(raw_claim_mapping.get("name", "name")),
        first_name=str(raw_claim_mapping.get("first_name", "first_name")),
        last_name=str(raw_claim_mapping.get("last_name", "last_name")),
        groups=str(raw_claim_mapping.get("groups", "groups")),
        extra_fields={
            str(key): str(value)
            for key, value in raw_extra_fields.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if isinstance(raw_extra_fields, dict)
        else {},
    )
    return SAMLProviderConfig(
        entity_id=str(payload["entity_id"]),
        sso_url=str(payload["sso_url"]),
        x509_certificate=str(payload["x509_certificate"]),
        slo_url=str(payload["slo_url"]) if payload.get("slo_url") else None,
        audience=str(payload["audience"]) if payload.get("audience") else None,
        idp_metadata_xml=str(payload["idp_metadata_xml"]) if payload.get("idp_metadata_xml") else None,
        name_id_format=str(payload["name_id_format"]) if payload.get("name_id_format") else None,
        binding=str(payload.get("binding", "redirect")),
        allow_idp_initiated=bool(payload.get("allow_idp_initiated", False)),
        want_assertions_signed=bool(payload.get("want_assertions_signed", True)),
        sign_authn_request=bool(payload.get("sign_authn_request", True)),
        signature_algorithm=str(payload.get("signature_algorithm", "rsa-sha256")),
        digest_algorithm=str(payload.get("digest_algorithm", "sha256")),
        private_key=str(payload["private_key"]) if payload.get("private_key") else None,
        private_key_passphrase=(
            str(payload["private_key_passphrase"]) if payload.get("private_key_passphrase") else None
        ),
        signing_certificate=str(payload["signing_certificate"]) if payload.get("signing_certificate") else None,
        decryption_private_key=str(payload["decryption_private_key"])
        if payload.get("decryption_private_key")
        else None,
        decryption_private_key_passphrase=str(payload["decryption_private_key_passphrase"])
        if payload.get("decryption_private_key_passphrase")
        else None,
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


def choose_best_domain_match[DomainT: SSODomainProtocol](
    *,
    domain: str,
    domains: list[DomainT],
) -> DomainT | None:
    exact_matches = [item for item in domains if item.domain == domain]
    if len(exact_matches) > 1:
        msg = f"multiple providers match domain '{domain}'"
        raise ValueError(msg)
    if exact_matches:
        return exact_matches[0]

    suffix_matches = [item for item in domains if domain.endswith(f".{item.domain}")]
    if not suffix_matches:
        return None

    max_length = max(len(item.domain) for item in suffix_matches)
    best_matches = [item for item in suffix_matches if len(item.domain) == max_length]
    if len(best_matches) > 1:
        msg = f"multiple providers match domain '{domain}'"
        raise ValueError(msg)
    return best_matches[0]


def choose_best_verified_domain_match[DomainT: SSODomainProtocol](
    *,
    domain: str,
    domains: list[DomainT],
) -> DomainT | None:
    try:
        return choose_best_domain_match(domain=domain, domains=domains)
    except ValueError as exc:
        msg = str(exc).replace("multiple providers", "multiple verified providers")
        raise ValueError(msg) from exc


def mask_client_id(client_id: str | None) -> str | None:
    if client_id is None:
        return None
    if len(client_id) <= _MASKED_CLIENT_ID_VISIBLE_CHARS:
        return "****"
    return f"****{client_id[-_MASKED_CLIENT_ID_VISIBLE_CHARS:]}"


def fingerprint_certificate(certificate: str | None) -> str | None:
    if certificate is None:
        return None
    lines = [
        line.strip()
        for line in certificate.strip().splitlines()
        if line.strip() and "BEGIN CERTIFICATE" not in line and "END CERTIFICATE" not in line
    ]
    if not lines:
        return None
    return sha256("".join(lines).encode("utf-8")).hexdigest()


def _normalize_origin(origin: str) -> tuple[str, str]:
    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.netloc or parsed.scheme.lower() not in _HTTP_SCHEMES:
        msg = "origin must be an absolute http(s) URL"
        raise ValueError(msg)
    return parsed.scheme.lower(), parsed.netloc.lower()


def _is_callback_path(path: str) -> bool:
    normalized_path = path.rstrip("/")
    return (
        normalized_path.endswith(("/auth/provider/sso/callback", "/auth/provider/sso/acs", "/auth/provider/sso/slo"))
        or "/auth/provider/sso/callback/" in normalized_path
        or "/auth/provider/sso/acs/" in normalized_path
        or "/auth/provider/sso/slo/" in normalized_path
    )
