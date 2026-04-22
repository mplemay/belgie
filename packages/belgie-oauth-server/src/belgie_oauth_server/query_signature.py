"""HMAC-SHA256 signing for oauth_query strings (Better Auth compatible).

See better-auth: ``makeSignature`` in better-auth/src/crypto, ``verifyOAuthQueryParams`` in
oauth-provider ``utils`` and ``signParams``/``serializeAuthorizationQuery`` in ``authorize``."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import TYPE_CHECKING, TypedDict
from urllib.parse import parse_qsl, quote_plus, urlencode

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "build_signed_oauth_query",
    "make_signature",
    "parse_verified_oauth_query",
    "verify_oauth_query_params",
]


def make_signature(value: str, secret: str) -> str:
    """HMAC-SHA256 over ``value`` with ``secret``; return standard base64 (matches JS ``btoa``)."""
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_oauth_query_params(oauth_query: str, secret: str) -> bool:
    """Validate ``exp`` and ``sig`` on an oauth_query string (Better Auth)."""
    pairs = parse_qsl(oauth_query, keep_blank_values=True)
    sig: str | None = None
    for key, value in pairs:
        if key == "sig":
            sig = value
    if not sig or not any(key == "exp" for key, _ in pairs):
        return False
    to_sign = _pairs_to_signing_string(pairs, exclude_sig=True)
    if not to_sign:
        return False
    try:
        exp_num = int(next(value for key, value in pairs if key == "exp"))
    except (StopIteration, ValueError):
        return False
    if exp_num * 1000 < time.time() * 1000:
        return False
    return hmac.compare_digest(sig, make_signature(to_sign, secret))


def _pairs_to_signing_string(pairs: list[tuple[str, str]], *, exclude_sig: bool) -> str:
    filtered = [(k, v) for k, v in pairs if (not exclude_sig or k != "sig")]
    if not exclude_sig and any(k == "sig" for k, _ in filtered):
        return ""
    return urlencode(filtered, doseq=True, quote_via=quote_plus)


class AuthorizationQueryParts(TypedDict, total=False):
    response_type: str
    request_uri: str
    redirect_uri: str
    scope: str
    state: str
    client_id: str
    prompt: str
    display: str
    ui_locales: str
    max_age: str
    acr_values: str
    login_hint: str
    id_token_hint: str
    code_challenge: str
    code_challenge_method: str
    nonce: str
    resource: str


# Object.entries order in oauthAuthorizationQuerySchema (z) + common passthrough
_CANONICAL_QUERY_KEYS: tuple[str, ...] = (
    "response_type",
    "request_uri",
    "redirect_uri",
    "scope",
    "state",
    "client_id",
    "prompt",
    "display",
    "ui_locales",
    "max_age",
    "acr_values",
    "login_hint",
    "id_token_hint",
    "code_challenge",
    "code_challenge_method",
    "nonce",
    "resource",
)


def build_signed_oauth_query(
    parts: Mapping[str, str | list[str] | None],
    *,
    secret: str,
    code_expires_in_seconds: int,
    extra: Mapping[str, str | list[str] | None] | None = None,
) -> str:
    """Build ``&exp=`` and ``&sig=`` over a query string in Better Auth's canonical key order.

    Scalars and lists (for repeated keys) are serialized with the same key order as
    ``serializeAuthorizationQuery``; unknown keys are appended in sorted order at the end.
    """
    merged: dict[str, str | list[str] | None] = {**dict(parts), **(dict(extra) if extra else {})}
    pairs: list[tuple[str, str]] = _flatten_oauth_query_parts(merged, include_unknown=True)
    if not any(k == "exp" for k, _ in pairs):
        iat = int(time.time())
        exp = iat + int(code_expires_in_seconds)
        pairs = [(k, v) for k, v in pairs if k != "exp"]
        pairs.append(("exp", str(exp)))
    to_sign = _pairs_to_signing_string(pairs, exclude_sig=False)
    signature = make_signature(to_sign, secret)
    return f"{to_sign}&sig={quote_plus(signature)}"


def _flatten_oauth_query_parts(
    merged: Mapping[str, str | list[str] | None],
    *,
    include_unknown: bool,
) -> list[tuple[str, str]]:
    known: set[str] = set(_CANONICAL_QUERY_KEYS)
    pairs: list[tuple[str, str]] = []
    for key in _CANONICAL_QUERY_KEYS:
        if key not in merged:
            continue
        value = merged[key]
        if value is None:
            continue
        if isinstance(value, list):
            pairs.extend((key, str(item)) for item in value)
        else:
            pairs.append((key, str(value)))
    if include_unknown:
        extras = [k for k in merged if k not in known and k not in ("exp", "sig")]
        for key in sorted(extras):
            value = merged.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                pairs.extend((key, str(item)) for item in value)
            else:
                pairs.append((key, str(value)))
    return pairs


def parse_verified_oauth_query(
    oauth_query: str,
    secret: str,
) -> dict[str, str] | None:
    """If valid, return query parameters as a dict (last value wins; ``sig`` omitted)."""
    if not verify_oauth_query_params(oauth_query, secret):
        return None
    pairs = parse_qsl(oauth_query, keep_blank_values=True)
    return {k: v for k, v in pairs if k != "sig"}
