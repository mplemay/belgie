from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


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
