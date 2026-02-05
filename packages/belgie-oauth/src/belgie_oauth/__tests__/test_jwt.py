import base64

from belgie_oauth.jwt import JwtSignOptions, build_oct_jwks, sign_hs256, verify_hs256


def test_sign_and_verify_hs256() -> None:
    secret = "super-secret"  # noqa: S105
    token = sign_hs256(
        {"sub": "user-123"},
        secret=secret,
        options=JwtSignOptions(
            issuer="https://issuer.example",
            audience="aud",
            expires_in=120,
        ),
    )
    claims = verify_hs256(
        token,
        secret=secret,
        issuer="https://issuer.example",
        audience="aud",
    )
    assert claims["sub"] == "user-123"
    assert "iat" in claims
    assert "exp" in claims


def test_build_oct_jwks() -> None:
    secret = "secret"  # noqa: S105
    jwks = build_oct_jwks(secret, key_id="kid-1")
    assert jwks["keys"]
    key = jwks["keys"][0]
    assert key["kty"] == "oct"
    assert key["alg"] == "HS256"
    assert key["use"] == "sig"
    assert key["kid"] == "kid-1"
    expected = base64.urlsafe_b64encode(secret.encode("utf-8")).rstrip(b"=").decode("utf-8")
    assert key["k"] == expected
