from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

from jose import jwt


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


@dataclass(slots=True, kw_only=True, frozen=True)
class JwtSignOptions:
    issuer: str | None = None
    audience: str | None = None
    expires_in: int | None = None
    issued_at: int | None = None
    key_id: str | None = None


def build_oct_jwks(secret: str, *, key_id: str = "belgie") -> dict[str, Any]:
    return {
        "keys": [
            {
                "kty": "oct",
                "k": _b64url(secret.encode("utf-8")),
                "alg": "HS256",
                "use": "sig",
                "kid": key_id,
            },
        ],
    }


def sign_hs256(payload: dict[str, Any], *, secret: str, options: JwtSignOptions | None = None) -> str:
    signing_options = options or JwtSignOptions()
    iat = signing_options.issued_at if signing_options.issued_at is not None else int(time.time())
    claims = dict(payload)
    claims.setdefault("iat", iat)
    if signing_options.issuer:
        claims.setdefault("iss", signing_options.issuer)
    if signing_options.audience:
        claims.setdefault("aud", signing_options.audience)
    if signing_options.expires_in is not None:
        claims.setdefault("exp", iat + signing_options.expires_in)
    headers = {"alg": "HS256"}
    if signing_options.key_id:
        headers["kid"] = signing_options.key_id
    return jwt.encode(claims, secret, algorithm="HS256", headers=headers)


def verify_hs256(
    token: str,
    *,
    secret: str,
    issuer: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    options = {
        "verify_aud": audience is not None,
        "verify_iss": issuer is not None,
    }
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=audience,
        issuer=issuer,
        options=options,
    )
