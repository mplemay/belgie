from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import httpx
from belgie_oauth._transport import OAuthTransport
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig

from belgie_sso.utils import _normalize_origin, normalize_http_url, normalize_issuer, resolve_http_url

if TYPE_CHECKING:
    from collections.abc import Mapping

    from belgie_oauth._types import ProviderMetadata
    from belgie_proto.core.json import JSONValue

type DiscoveryErrorCode = Literal[
    "discovery_timeout",
    "discovery_not_found",
    "discovery_invalid_json",
    "discovery_invalid_url",
    "discovery_untrusted_origin",
    "issuer_mismatch",
    "discovery_incomplete",
    "unsupported_token_auth_method",
    "discovery_unexpected_error",
]

_REQUIRED_DISCOVERY_FIELDS = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
_OPTIONAL_DISCOVERY_ENDPOINT_FIELDS = (
    "userinfo_endpoint",
    "revocation_endpoint",
    "end_session_endpoint",
    "introspection_endpoint",
)
_SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS = ("client_secret_basic", "client_secret_post")
_DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD = _SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS[0]
_DISCOVERY_TIMEOUT: DiscoveryErrorCode = "discovery_timeout"
_DISCOVERY_NOT_FOUND: DiscoveryErrorCode = "discovery_not_found"
_DISCOVERY_INVALID_JSON: DiscoveryErrorCode = "discovery_invalid_json"
_DISCOVERY_INVALID_URL: DiscoveryErrorCode = "discovery_invalid_url"
_DISCOVERY_UNTRUSTED_ORIGIN: DiscoveryErrorCode = "discovery_untrusted_origin"
_ISSUER_MISMATCH: DiscoveryErrorCode = "issuer_mismatch"
_DISCOVERY_INCOMPLETE: DiscoveryErrorCode = "discovery_incomplete"
_UNSUPPORTED_TOKEN_AUTH_METHOD: DiscoveryErrorCode = "unsupported_token_auth_method"  # noqa: S105
_DISCOVERY_UNEXPECTED_ERROR: DiscoveryErrorCode = "discovery_unexpected_error"


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCDiscoveryResult:
    issuer: str
    config: OIDCProviderConfig


class DiscoveryError(Exception):
    def __init__(
        self,
        code: DiscoveryErrorCode,
        message: str,
        *,
        details: dict[str, JSONValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else dict(details)


def _coerce_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def compute_discovery_url(issuer: str) -> str:
    return f"{normalize_issuer(issuer)}/.well-known/openid-configuration"


def validate_discovery_url(
    *,
    discovery_url: str,
    issuer: str,
    trusted_origins: tuple[str, ...] = (),
) -> str:
    try:
        normalized_discovery_url = normalize_http_url(discovery_url, field_name="discovery_endpoint")
    except ValueError as exc:
        msg = f'The url "discovery_endpoint" must be valid: {discovery_url}'
        raise DiscoveryError(
            _DISCOVERY_INVALID_URL,
            msg,
            details={"url": discovery_url},
        ) from exc

    allowed_origins = {
        _normalize_origin(normalize_issuer(issuer)),
        *(_normalize_origin(origin) for origin in trusted_origins),
    }
    if _normalize_origin(normalized_discovery_url) not in allowed_origins:
        msg = (
            f'The main discovery endpoint "{normalized_discovery_url}" '
            "is not trusted by your trusted origins configuration."
        )
        raise DiscoveryError(
            _DISCOVERY_UNTRUSTED_ORIGIN,
            msg,
            details={"url": normalized_discovery_url},
        )
    return normalized_discovery_url


async def fetch_discovery_document(
    *,
    discovery_url: str,
    timeout_seconds: float,
) -> Mapping[str, object]:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as http_client:
            response = await http_client.get(discovery_url)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        msg = "Discovery request timed out"
        raise DiscoveryError(
            _DISCOVERY_TIMEOUT,
            msg,
            details={"url": discovery_url, "timeout_seconds": timeout_seconds},
        ) from exc
    except httpx.HTTPStatusError as exc:
        if (status_code := exc.response.status_code) == httpx.codes.NOT_FOUND:
            msg = "Discovery endpoint not found"
            raise DiscoveryError(
                _DISCOVERY_NOT_FOUND,
                msg,
                details={"url": discovery_url, "status_code": status_code},
            ) from exc
        if status_code == httpx.codes.REQUEST_TIMEOUT:
            msg = "Discovery request timed out"
            raise DiscoveryError(
                _DISCOVERY_TIMEOUT,
                msg,
                details={
                    "url": discovery_url,
                    "timeout_seconds": timeout_seconds,
                    "status_code": status_code,
                },
            ) from exc
        msg = f"Unexpected discovery error: HTTP {status_code}"
        raise DiscoveryError(
            _DISCOVERY_UNEXPECTED_ERROR,
            msg,
            details={"url": discovery_url, "status_code": status_code},
        ) from exc
    except httpx.HTTPError as exc:
        msg = f"Unexpected error during discovery: {exc}"
        raise DiscoveryError(
            _DISCOVERY_UNEXPECTED_ERROR,
            msg,
            details={"url": discovery_url},
        ) from exc

    try:
        document = response.json()
    except ValueError as exc:
        msg = "Discovery endpoint returned invalid JSON"
        raise DiscoveryError(
            _DISCOVERY_INVALID_JSON,
            msg,
            details={"url": discovery_url},
        ) from exc

    if not isinstance(document, dict):
        msg = "Discovery endpoint returned invalid JSON"
        raise DiscoveryError(
            _DISCOVERY_INVALID_JSON,
            msg,
            details={"url": discovery_url},
        )

    return document


def validate_discovery_document(
    *,
    metadata: Mapping[str, object],
    issuer: str,
) -> None:
    missing_fields = [
        field for field in _REQUIRED_DISCOVERY_FIELDS if _coerce_optional_string(metadata.get(field)) is None
    ]
    if missing_fields:
        msg = f"Discovery document is missing required fields: {', '.join(missing_fields)}"
        raise DiscoveryError(
            _DISCOVERY_INCOMPLETE,
            msg,
            details={"missing_fields": list(missing_fields)},
        )

    raw_discovered_issuer = _coerce_optional_string(metadata.get("issuer"))
    if raw_discovered_issuer is None:
        msg = "Discovery document is missing required fields: issuer"
        raise DiscoveryError(
            _DISCOVERY_INCOMPLETE,
            msg,
            details={"missing_fields": ["issuer"]},
        )
    try:
        discovered_issuer = normalize_issuer(raw_discovered_issuer)
    except ValueError as exc:
        msg = f'The url "issuer" must be valid: {raw_discovered_issuer}'
        raise DiscoveryError(
            _DISCOVERY_INVALID_URL,
            msg,
            details={"url": raw_discovered_issuer, "field": "issuer"},
        ) from exc

    if discovered_issuer != normalize_issuer(issuer):
        msg = f'Discovered issuer "{raw_discovered_issuer}" does not match configured issuer "{issuer}"'
        raise DiscoveryError(
            _ISSUER_MISMATCH,
            msg,
            details={"discovered": raw_discovered_issuer, "configured": issuer},
        )


def normalize_oidc_metadata(
    *,
    metadata: Mapping[str, object],
    issuer: str,
    discovery_endpoint: str | None = None,
    trusted_origins: tuple[str, ...] = (),
) -> dict[str, str | None]:
    normalized_issuer = normalize_issuer(issuer)
    discovered_issuer = _coerce_optional_string(metadata.get("issuer")) or normalized_issuer
    try:
        normalized_discovered_issuer = normalize_issuer(discovered_issuer)
    except ValueError as exc:
        msg = f'The url "issuer" must be valid: {discovered_issuer}'
        raise DiscoveryError(
            _DISCOVERY_INVALID_URL,
            msg,
            details={"url": discovered_issuer, "field": "issuer"},
        ) from exc
    if normalized_discovered_issuer != normalized_issuer:
        msg = f'Discovered issuer "{discovered_issuer}" does not match configured issuer "{issuer}"'
        raise DiscoveryError(
            _ISSUER_MISMATCH,
            msg,
            details={"discovered": discovered_issuer, "configured": issuer},
        )

    allowed_origins = {
        _normalize_origin(normalized_issuer),
        *(_normalize_origin(origin) for origin in trusted_origins),
    }
    if discovery_endpoint is not None:
        try:
            allowed_origins.add(
                _normalize_origin(
                    normalize_http_url(discovery_endpoint, field_name="discovery_endpoint"),
                ),
            )
        except ValueError as exc:
            msg = f'The url "discovery_endpoint" must be valid: {discovery_endpoint}'
            raise DiscoveryError(
                _DISCOVERY_INVALID_URL,
                msg,
                details={"url": discovery_endpoint},
            ) from exc

    normalized: dict[str, str | None] = {"issuer": normalized_issuer}
    for key in (*_REQUIRED_DISCOVERY_FIELDS[1:], *_OPTIONAL_DISCOVERY_ENDPOINT_FIELDS):
        raw_value = _coerce_optional_string(metadata.get(key))
        if raw_value is None:
            if key in _REQUIRED_DISCOVERY_FIELDS[1:]:
                msg = f"missing required discovery field: {key}"
                raise DiscoveryError(
                    _DISCOVERY_INCOMPLETE,
                    msg,
                    details={"missing_fields": [key]},
                )
            normalized[key] = None
            continue
        try:
            resolved = resolve_http_url(raw_value, base_url=normalized_issuer, field_name=key)
        except ValueError as exc:
            msg = f'The url "{key}" must be valid: {raw_value}'
            raise DiscoveryError(
                _DISCOVERY_INVALID_URL,
                msg,
                details={"url": raw_value, "field": key},
            ) from exc
        if _normalize_origin(resolved) not in allowed_origins:
            msg = f'The {key} "{resolved}" is not trusted by your trusted origins configuration.'
            raise DiscoveryError(
                _DISCOVERY_UNTRUSTED_ORIGIN,
                msg,
                details={"endpoint": key, "url": resolved},
            )
        normalized[key] = resolved
    return normalized


def needs_runtime_discovery(config: OIDCProviderConfig) -> bool:
    return config.authorization_endpoint is None or config.token_endpoint is None or config.jwks_uri is None


def select_token_endpoint_auth_method(
    *,
    requested_method: str,
    supported_methods: object,
) -> str:
    if requested_method not in _SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS:
        msg = f"token endpoint auth method '{requested_method}' is not supported"
        raise DiscoveryError(
            _UNSUPPORTED_TOKEN_AUTH_METHOD,
            msg,
            details={"requested_method": requested_method},
        )

    if not isinstance(supported_methods, list):
        return requested_method

    normalized_supported_methods = [
        method
        for raw_method in supported_methods
        if isinstance(raw_method, str)
        for method in [raw_method.strip()]
        if method
    ]
    if requested_method in normalized_supported_methods:
        return requested_method
    if _DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD in normalized_supported_methods:
        return _DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD
    if "client_secret_post" in normalized_supported_methods:
        return "client_secret_post"
    return _DEFAULT_TOKEN_ENDPOINT_AUTH_METHOD


async def discover_oidc_configuration(  # noqa: PLR0913
    *,
    issuer: str,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    token_endpoint_auth_method: str,
    claim_mapping: OIDCClaimMapping,
    timeout_seconds: float,
    discovery_endpoint: str | None = None,
    trusted_origins: tuple[str, ...] = (),
    use_pkce: bool = True,
    override_user_info_on_sign_in: bool = False,
) -> OIDCDiscoveryResult:
    normalized_issuer = normalize_issuer(issuer)
    discovery_url = validate_discovery_url(
        discovery_url=discovery_endpoint or compute_discovery_url(normalized_issuer),
        issuer=normalized_issuer,
        trusted_origins=trusted_origins,
    )
    document = await fetch_discovery_document(
        discovery_url=discovery_url,
        timeout_seconds=timeout_seconds,
    )
    validate_discovery_document(
        metadata=document,
        issuer=normalized_issuer,
    )

    normalized_metadata = normalize_oidc_metadata(
        metadata=document,
        issuer=normalized_issuer,
        discovery_endpoint=discovery_url,
        trusted_origins=trusted_origins,
    )
    selected_token_endpoint_auth_method = select_token_endpoint_auth_method(
        requested_method=token_endpoint_auth_method,
        supported_methods=document.get("token_endpoint_auth_methods_supported"),
    )

    return OIDCDiscoveryResult(
        issuer=normalized_issuer,
        config=OIDCProviderConfig(
            issuer=normalized_issuer,
            client_id=client_id,
            client_secret=client_secret,
            authorization_endpoint=normalized_metadata["authorization_endpoint"],
            token_endpoint=normalized_metadata["token_endpoint"],
            userinfo_endpoint=normalized_metadata["userinfo_endpoint"],
            discovery_endpoint=discovery_url,
            jwks_uri=normalized_metadata["jwks_uri"],
            scopes=tuple(scopes),
            token_endpoint_auth_method=selected_token_endpoint_auth_method,
            use_pkce=use_pkce,
            override_user_info_on_sign_in=override_user_info_on_sign_in,
            claim_mapping=claim_mapping,
        ),
    )


async def ensure_runtime_discovery(
    *,
    config: OIDCProviderConfig,
    timeout_seconds: float,
    trusted_origins: tuple[str, ...] = (),
) -> OIDCProviderConfig:
    if not needs_runtime_discovery(config):
        return config

    discovery = await discover_oidc_configuration(
        issuer=config.issuer,
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=list(config.scopes),
        token_endpoint_auth_method=config.token_endpoint_auth_method,
        claim_mapping=config.claim_mapping,
        timeout_seconds=timeout_seconds,
        discovery_endpoint=config.discovery_endpoint,
        trusted_origins=trusted_origins,
        use_pkce=config.use_pkce,
        override_user_info_on_sign_in=config.override_user_info_on_sign_in,
    )
    return OIDCProviderConfig(
        issuer=config.issuer,
        client_id=config.client_id,
        client_secret=config.client_secret,
        authorization_endpoint=config.authorization_endpoint or discovery.config.authorization_endpoint,
        token_endpoint=config.token_endpoint or discovery.config.token_endpoint,
        userinfo_endpoint=config.userinfo_endpoint or discovery.config.userinfo_endpoint,
        discovery_endpoint=config.discovery_endpoint or discovery.config.discovery_endpoint,
        jwks_uri=config.jwks_uri or discovery.config.jwks_uri,
        scopes=config.scopes,
        token_endpoint_auth_method=config.token_endpoint_auth_method,
        use_pkce=config.use_pkce,
        override_user_info_on_sign_in=config.override_user_info_on_sign_in,
        claim_mapping=config.claim_mapping,
    )


class ValidatingOAuthTransport(OAuthTransport):
    def __init__(
        self,
        *args: object,
        issuer: str,
        discovery_endpoint: str | None,
        trusted_origins: tuple[str, ...],
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._issuer = issuer
        self._discovery_endpoint = discovery_endpoint
        self._trusted_origins = trusted_origins

    async def resolve_server_metadata(self) -> ProviderMetadata:
        if self._discovery_endpoint is not None:
            validate_discovery_url(
                discovery_url=self._discovery_endpoint,
                issuer=self._issuer,
                trusted_origins=self._trusted_origins,
            )
        try:
            metadata = await super().resolve_server_metadata()
        except httpx.TimeoutException as exc:
            msg = "Discovery request timed out"
            raise DiscoveryError(
                _DISCOVERY_TIMEOUT,
                msg,
                details={"url": self._discovery_endpoint or compute_discovery_url(self._issuer)},
            ) from exc
        except httpx.HTTPStatusError as exc:
            if (status_code := exc.response.status_code) == httpx.codes.NOT_FOUND:
                msg = "Discovery endpoint not found"
                raise DiscoveryError(
                    _DISCOVERY_NOT_FOUND,
                    msg,
                    details={
                        "url": self._discovery_endpoint or compute_discovery_url(self._issuer),
                        "status_code": status_code,
                    },
                ) from exc
            msg = f"Unexpected discovery error: HTTP {status_code}"
            raise DiscoveryError(
                _DISCOVERY_UNEXPECTED_ERROR,
                msg,
                details={
                    "url": self._discovery_endpoint or compute_discovery_url(self._issuer),
                    "status_code": status_code,
                },
            ) from exc
        except ValueError as exc:
            msg = "Discovery endpoint returned invalid JSON"
            raise DiscoveryError(
                _DISCOVERY_INVALID_JSON,
                msg,
                details={"url": self._discovery_endpoint or compute_discovery_url(self._issuer)},
            ) from exc
        except httpx.HTTPError as exc:
            msg = f"Unexpected error during discovery: {exc}"
            raise DiscoveryError(
                _DISCOVERY_UNEXPECTED_ERROR,
                msg,
                details={"url": self._discovery_endpoint or compute_discovery_url(self._issuer)},
            ) from exc
        normalized = normalize_oidc_metadata(
            metadata=metadata,
            issuer=self._issuer,
            discovery_endpoint=self._discovery_endpoint,
            trusted_origins=self._trusted_origins,
        )
        resolved = dict(metadata)
        resolved.update(normalized)
        return resolved
