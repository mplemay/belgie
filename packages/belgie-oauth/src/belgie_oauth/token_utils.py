from __future__ import annotations

import hashlib
import hmac


def hash_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def apply_prefix(token: str, prefix: str | None) -> str:
    if not prefix:
        return token
    return f"{prefix}{token}"


def strip_prefix(token: str, prefix: str | None) -> str:
    if not prefix:
        return token
    if token.startswith(prefix):
        return token[len(prefix) :]
    msg = "token does not contain expected prefix"
    raise ValueError(msg)
