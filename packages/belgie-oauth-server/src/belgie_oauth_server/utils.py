from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable  # noqa: TC003
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import Request  # noqa: TC002


def construct_redirect_uri(redirect_uri_base: str, **params: str | None) -> str:
    parsed_uri = urlparse(redirect_uri_base)
    query_params = [(key, value) for key, values in parse_qs(parsed_uri.query).items() for value in values]
    for key, value in params.items():
        if value is not None:
            query_params.append((key, value))
    return urlunparse(parsed_uri._replace(query=urlencode(query_params)))


def join_url(base_url: str, path: str) -> str:
    parsed = urlparse(base_url)
    base_path = parsed.path.rstrip("/")
    append_path = path.lstrip("/")
    joined_path = f"{base_path}/{append_path}" if append_path else base_path
    return urlunparse(parsed._replace(path=joined_path))


def create_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")


def urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def is_loopback_host(hostname: str | None) -> bool:
    return hostname in {"127.0.0.1", "::1", "localhost"}


def is_safe_redirect_uri(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme in {"javascript", "data", "vbscript"}:
        return False
    if parsed.scheme in {"http", "https"}:
        if parsed.scheme == "https":
            return True
        return is_loopback_host(parsed.hostname)
    return bool(parsed.scheme)


def validate_safe_redirect_uri(value: str) -> str:
    if not is_safe_redirect_uri(value):
        msg = f"Redirect URI '{value}' is not allowed"
        raise ValueError(msg)
    return value


def redirect_uris_match(registered_uri: str, requested_uri: str) -> bool:
    if registered_uri == requested_uri:
        return True

    registered = urlparse(registered_uri)
    requested = urlparse(requested_uri)
    if not (
        registered.scheme == requested.scheme
        and registered.hostname == requested.hostname
        and registered.path == requested.path
        and registered.query == requested.query
        and registered.fragment == requested.fragment
    ):
        return False
    return is_loopback_host(registered.hostname)


def dedupe_scopes(scopes: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for scope in scopes:
        normalized = scope.strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def parse_scope_string(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return dedupe_scopes(value.split(" "))


def is_fetch_request(request: Request) -> bool:
    sec_fetch_mode = request.headers.get("sec-fetch-mode", "").lower()
    accept = request.headers.get("accept", "").lower()
    if sec_fetch_mode == "navigate":
        return False
    if "application/json" in accept:
        return True
    return bool(sec_fetch_mode and sec_fetch_mode != "navigate")
