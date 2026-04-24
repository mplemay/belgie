from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from joserfc import jwt
from joserfc.jwk import RSAKey

if TYPE_CHECKING:
    from belgie_proto.core.json import JSONValue


def build_rsa_signing_key(*, kid: str = "test-key"):
    return RSAKey.generate_key(key_size=2048, parameters={"kid": kid}, private=True, auto_kid=False)


def build_jwks_document(signing_key) -> dict[str, list[dict[str, str]]]:
    return {"keys": [signing_key.as_dict(private=False)]}


def issue_id_token(
    *,
    signing_key,
    issuer: str,
    audience: str | list[str],
    subject: str,
    nonce: str,
    claims: dict[str, JSONValue],
) -> str:
    now = datetime.now(UTC)
    if isinstance(audience, str):
        audience_value: JSONValue = audience
    else:
        audience_list: list[JSONValue] = list(audience)
        audience_value = audience_list

    payload: dict[str, JSONValue] = {}
    payload["iss"] = issuer
    payload["aud"] = audience_value
    payload["sub"] = subject
    payload["iat"] = int(now.timestamp())
    payload["exp"] = int((now + timedelta(minutes=5)).timestamp())
    payload["nonce"] = nonce
    payload.update(claims)
    return jwt.encode(
        {"alg": "RS256", "kid": signing_key.as_dict(private=False)["kid"]},
        payload,
        signing_key,
    )
