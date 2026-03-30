from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
from typing import TYPE_CHECKING, overload
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from typing_extensions import TypeIs

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from uuid import UUID


@overload
async def maybe_await[T](value: Awaitable[T]) -> T: ...


@overload
async def maybe_await[T](value: T) -> T: ...


async def maybe_await(value):
    if not _is_awaitable(value):
        return value
    return await value


def normalize_relative_or_same_origin_url(url: str, *, base_url: str) -> str | None:
    parsed = urlparse(url)
    base = urlparse(base_url)
    base_origin = (base.scheme.lower(), base.netloc.lower())

    if not parsed.scheme and not parsed.netloc:
        if url.startswith("/") and not url.startswith("//"):
            return url
        return None

    if (parsed.scheme.lower(), parsed.netloc.lower()) != base_origin:
        return None

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def absolute_url(base_url: str, path_or_url: str) -> str:
    parsed = urlparse(path_or_url)
    if parsed.scheme and parsed.netloc:
        return path_or_url
    base = urlparse(base_url)
    base_path = base.path.rstrip("/")
    relative_path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"
    path = f"{base_path}{relative_path}" if base_path else relative_path
    return urlunparse((base.scheme, base.netloc, path, parsed.params, parsed.query, parsed.fragment))


def sign_success_token(*, secret: str, subscription_id: UUID, redirect_to: str) -> str:
    payload = json.dumps(
        {"subscription_id": str(subscription_id), "redirect_to": redirect_to},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_urlsafe_encode(payload)}.{_urlsafe_encode(digest)}"


def unsign_success_token(*, secret: str, token: str) -> tuple[str, str]:
    try:
        encoded_payload, encoded_digest = token.split(".", maxsplit=1)
    except ValueError as exc:
        msg = "invalid success token"
        raise ValueError(msg) from exc

    payload = _urlsafe_decode(encoded_payload)
    provided_digest = _urlsafe_decode(encoded_digest)
    expected_digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_digest, expected_digest):
        msg = "invalid success token"
        raise ValueError(msg)

    decoded = json.loads(payload)
    subscription_id = decoded.get("subscription_id")
    redirect_to = decoded.get("redirect_to")
    if not isinstance(subscription_id, str) or not isinstance(redirect_to, str):
        msg = "invalid success token"
        raise ValueError(msg)  # noqa: TRY004
    return subscription_id, redirect_to


def append_query_params(url: str, **params: str) -> str:
    parsed = urlparse(url)
    current_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    current_params.update(params)
    return urlunparse(parsed._replace(query=urlencode(current_params)))


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _is_awaitable[T](value: T | Awaitable[T]) -> TypeIs[Awaitable[T]]:
    return inspect.isawaitable(value)
