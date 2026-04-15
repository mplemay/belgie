from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel, SecretStr

from belgie_oauth_server.utils import urlsafe_b64encode

type SigningAlgorithm = Literal["RS256", "HS256"]


class OAuthServerSigning(BaseModel):
    algorithm: SigningAlgorithm = "HS256"
    key_id: str | None = None
    private_key_pem: SecretStr | None = None
    public_key_pem: SecretStr | None = None


@dataclass(frozen=True, slots=True)
class OAuthServerSigningState:
    algorithm: SigningAlgorithm
    key_id: str
    signing_key: str | bytes
    verification_key: str | bytes
    jwk: dict[str, Any] | None = None

    def sign(self, payload: dict[str, Any]) -> str:
        headers = {"alg": self.algorithm, "kid": self.key_id}
        return jwt.encode(payload, self.signing_key, algorithm=self.algorithm, headers=headers)

    def decode(
        self,
        token: str,
        *,
        audience: str | list[str] | None = None,
        issuer: str | None = None,
        verify_exp: bool = True,
    ) -> dict[str, Any]:
        options = {
            "verify_exp": verify_exp,
            "verify_aud": audience is not None,
            "verify_iss": issuer is not None,
        }
        return jwt.decode(
            token,
            self.verification_key,
            algorithms=[self.algorithm],
            audience=audience,
            issuer=issuer,
            options=options,
        )

    @property
    def jwks(self) -> dict[str, list[dict[str, Any]]] | None:
        if self.jwk is None:
            return None
        return {"keys": [self.jwk]}


def build_signing_state(signing: OAuthServerSigning, fallback_secret: str) -> OAuthServerSigningState:
    if signing.algorithm == "HS256":
        secret = signing.private_key_pem.get_secret_value() if signing.private_key_pem is not None else fallback_secret
        key_id = signing.key_id or hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
        return OAuthServerSigningState(
            algorithm="HS256",
            key_id=key_id,
            signing_key=secret,
            verification_key=secret,
        )

    private_key = _load_rsa_private_key(signing.private_key_pem)
    public_key = (
        _load_rsa_public_key(signing.public_key_pem) if signing.public_key_pem is not None else private_key.public_key()
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    kid = signing.key_id or hashlib.sha256(public_pem).hexdigest()[:16]
    return OAuthServerSigningState(
        algorithm="RS256",
        key_id=kid,
        signing_key=private_pem,
        verification_key=public_pem,
        jwk=_rsa_public_jwk(public_key, kid),
    )


def _load_rsa_private_key(secret: SecretStr | None) -> rsa.RSAPrivateKey:
    if secret is None:
        msg = "signing.private_key_pem is required when signing.algorithm is RS256"
        raise ValueError(msg)

    return serialization.load_pem_private_key(
        secret.get_secret_value().encode("utf-8"),
        password=None,
    )


def _load_rsa_public_key(secret: SecretStr) -> rsa.RSAPublicKey:
    public_key = serialization.load_pem_public_key(secret.get_secret_value().encode("utf-8"))
    if not isinstance(public_key, rsa.RSAPublicKey):
        msg = "signing.public_key_pem must be an RSA public key"
        raise TypeError(msg)
    return public_key


def _rsa_public_jwk(public_key: rsa.RSAPublicKey, key_id: str) -> dict[str, Any]:
    public_numbers = public_key.public_numbers()
    e = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
    n = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id,
        "n": urlsafe_b64encode(n),
        "e": urlsafe_b64encode(e),
    }
