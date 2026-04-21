import base64
import hashlib
import re
import secrets
from dataclasses import asdict
from urllib.parse import urlencode, urlparse, urlunparse

from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig

_DOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_CLIENT_ID_SUFFIX_LENGTH = 4


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
    if not return_to:
        return None

    parsed_base_url = urlparse(base_url)
    base_origin = (parsed_base_url.scheme.lower(), parsed_base_url.netloc.lower())
    parsed = urlparse(return_to)

    if not parsed.scheme and not parsed.netloc:
        if return_to.startswith("/") and not return_to.startswith("//"):
            return return_to
        return None

    if (parsed.scheme.lower(), parsed.netloc.lower()) != base_origin:
        return None

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def domain_matches(search_domain: str, registered_domain: str) -> bool:
    search = search_domain.strip().lower().rstrip(".")
    registered = registered_domain.strip().lower().rstrip(".")
    return search == registered or search.endswith(f".{registered}")


def build_provider_callback_url(base_url: str, *, provider_id: str) -> str:
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    callback_path = f"/auth/provider/sso/callback/{provider_id}"
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
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
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
    if code_challenge:
        params["code_challenge"] = code_challenge
    if code_challenge_method:
        params["code_challenge_method"] = code_challenge_method

    parsed = urlparse(authorization_endpoint)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(params), ""))


def generate_pkce_code_verifier() -> str:
    return secrets.token_urlsafe(48)


def generate_pkce_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return default


def serialize_oidc_config(
    config: OIDCProviderConfig,
) -> dict[str, str | bool | list[str] | dict[str, str | dict[str, str]]]:
    payload = asdict(config)
    payload["scopes"] = list(config.scopes)
    return {key: value for key, value in payload.items() if value is not None}


def deserialize_oidc_config(
    payload: dict[str, str | bool | list[str] | dict[str, str | dict[str, str]]],
) -> OIDCProviderConfig:
    raw_claim_mapping = payload.get("claim_mapping", {})
    if not isinstance(raw_claim_mapping, dict):
        raw_claim_mapping = {}
    raw_extra_fields = raw_claim_mapping.get("extra_fields", {})
    if not isinstance(raw_extra_fields, dict):
        raw_extra_fields = {}
    claim_mapping = OIDCClaimMapping(
        subject=str(raw_claim_mapping.get("subject", "sub")),
        email=str(raw_claim_mapping.get("email", "email")),
        email_verified=str(raw_claim_mapping.get("email_verified", "email_verified")),
        name=str(raw_claim_mapping.get("name", "name")),
        image=str(raw_claim_mapping.get("image", "picture")),
        extra_fields={str(key): str(value) for key, value in raw_extra_fields.items() if isinstance(value, str)},
    )
    raw_scopes = payload.get("scopes", ["openid", "email", "profile"])
    if not isinstance(raw_scopes, list):
        raw_scopes = ["openid", "email", "profile"]
    scopes = tuple(scope for scope in raw_scopes if isinstance(scope, str))

    return OIDCProviderConfig(
        client_id=str(payload["client_id"]),
        client_secret=str(payload["client_secret"]),
        authorization_endpoint=(
            str(payload["authorization_endpoint"]) if payload.get("authorization_endpoint") is not None else None
        ),
        token_endpoint=str(payload["token_endpoint"]) if payload.get("token_endpoint") is not None else None,
        userinfo_endpoint=(str(payload["userinfo_endpoint"]) if payload.get("userinfo_endpoint") is not None else None),
        jwks_uri=str(payload["jwks_uri"]) if payload.get("jwks_uri") is not None else None,
        discovery_endpoint=(
            str(payload["discovery_endpoint"]) if payload.get("discovery_endpoint") is not None else None
        ),
        scopes=scopes,
        token_endpoint_auth_method=str(payload.get("token_endpoint_auth_method", "client_secret_basic")),
        claim_mapping=claim_mapping,
        pkce=_coerce_bool(payload.get("pkce"), default=True),
        override_user_info=_coerce_bool(payload.get("override_user_info"), default=False),
    )


def as_account_provider(provider_id: str) -> str:
    return f"sso:{provider_id}"


def parse_bool_claim(*, value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes"}


def mask_client_id(client_id: str) -> str:
    if len(client_id) <= _CLIENT_ID_SUFFIX_LENGTH:
        return "****"
    return f"****{client_id[-_CLIENT_ID_SUFFIX_LENGTH:]}"
