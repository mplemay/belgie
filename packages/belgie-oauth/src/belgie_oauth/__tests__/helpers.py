from __future__ import annotations

from datetime import UTC, datetime, timedelta

from authlib.jose import JsonWebKey, jwt


def build_rsa_signing_key(*, kid: str = "test-key"):
    return JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": kid})


def build_jwks_document(signing_key) -> dict[str, list[dict[str, str]]]:
    return {"keys": [signing_key.as_dict(is_private=False)]}


def issue_id_token(
    *,
    signing_key,
    issuer: str,
    audience: str | list[str],
    subject: str,
    nonce: str,
    claims: dict[str, object],
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": nonce,
    }
    payload.update(claims)
    token = jwt.encode(
        {"alg": "RS256", "kid": signing_key.as_dict(is_private=False)["kid"]},
        payload,
        signing_key,
    )
    return token.decode("ascii")
