from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from belgie_core.core.exceptions import ConfigurationError, OAuthError
from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:
    from belgie_oauth._types import JSONValue, SecretBoxPayload


def build_provider_callback_url(base_url: str, *, provider_id: str) -> str:
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            f"{path}/auth/provider/{provider_id}/callback",
            "",
            "",
            "",
        ),
    )


def build_provider_start_url(base_url: str, *, provider_id: str, token: str) -> str:
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            f"{path}/auth/provider/{provider_id}/start",
            "",
            urlencode({"token": token}),
            "",
        ),
    )


def append_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        ),
    )


def serialize_scopes(scopes: list[str]) -> str:
    return " ".join(dict.fromkeys(scopes))


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def normalize_client_id(value: str | list[str], *, field_name: str = "client_id") -> str | list[str]:
    if isinstance(value, str):
        if not value or not value.strip():
            msg = f"{field_name} must be a non-empty string"
            raise ValueError(msg)
        return value.strip()

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            msg = f"{field_name} entries must be non-empty strings"
            raise ValueError(msg)
        normalized.append(item.strip())

    if not normalized:
        msg = f"{field_name} must contain at least one non-empty string"
        raise ValueError(msg)

    return normalized


def primary_client_id(value: str | list[str]) -> str:
    if isinstance(value, str):
        return value
    return value[0]


def accepted_client_ids(value: str | list[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def coerce_optional_str(value: JSONValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SecretBox:
    def __init__(self, *, secret: str, label: str) -> None:
        if not secret:
            msg = f"{label} requires a secret"
            raise ConfigurationError(msg)
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encode(self, payload: SecretBoxPayload) -> str:
        serialized = json.dumps(payload, separators=(",", ":"))
        return self._fernet.encrypt(serialized.encode("utf-8")).decode("utf-8")

    def decode(self, token: str, *, error_message: str) -> dict[str, JSONValue]:
        try:
            data = self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise OAuthError(error_message) from exc
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise OAuthError(error_message)
        return parsed


class OAuthTokenCodec:
    _PREFIX = "enc:v1:"

    def __init__(self, *, enabled: bool, secret: str | None) -> None:
        self.enabled = enabled
        self._box: SecretBox | None = None
        if enabled:
            if not secret:
                msg = "token encryption requires a secret"
                raise ConfigurationError(msg)
            self._box = SecretBox(secret=secret, label="token encryption")

    def encode(self, value: str | None) -> str | None:
        if value is None or not self.enabled:
            return value
        if self._box is None:
            msg = "token encryption is not configured"
            raise ConfigurationError(msg)
        payload: dict[str, JSONValue] = {"value": value}
        encrypted = self._box.encode(payload)
        return f"{self._PREFIX}{encrypted}"

    def decode(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(self._PREFIX):
            return value
        if self._box is None:
            msg = "stored OAuth tokens are encrypted but decryption is not configured"
            raise OAuthError(msg)
        payload = self._box.decode(
            value.removeprefix(self._PREFIX),
            error_message="failed to decrypt stored OAuth tokens",
        )
        decoded = payload.get("value")
        return decoded if isinstance(decoded, str) else None
