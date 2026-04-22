from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey
from pydantic import BaseModel, SecretStr

from belgie_oauth_server.types import JSONValue  # noqa: TC001
from belgie_oauth_server.utils import urlsafe_b64encode

type SigningAlgorithm = Literal["RS256", "HS256"]


class OAuthServerSigning(BaseModel):
    algorithm: SigningAlgorithm = "HS256"
    key_id: str | None = None
    private_key_pem: SecretStr | None = None
    public_key_pem: SecretStr | None = None


class _NonExpiringClaimsRegistry(jwt.JWTClaimsRegistry):
    def validate_exp(self, value: int) -> None:
        pass


@dataclass(frozen=True, slots=True)
class OAuthServerSigningState:
    algorithm: SigningAlgorithm
    key_id: str
    signing_key: str | bytes
    verification_key: str | bytes
    jwk: dict[str, JSONValue] | None = None

    def sign(self, payload: dict[str, JSONValue]) -> str:
        return encode_jwt(payload, key=self.signing_key, algorithm=self.algorithm, key_id=self.key_id)

    def decode(
        self,
        token: str,
        *,
        audience: str | list[str] | None = None,
        issuer: str | None = None,
        verify_exp: bool = True,
        required_claims: list[str] | None = None,
    ) -> dict[str, JSONValue]:
        claims_options = _build_claims_options(
            audience=audience,
            issuer=issuer,
            required_claims=required_claims,
        )
        claims_registry_cls = jwt.JWTClaimsRegistry if verify_exp else _NonExpiringClaimsRegistry
        decoded_token = jwt.decode(
            token,
            key=_import_key(self.verification_key, self.algorithm),
            algorithms=[self.algorithm],
        )
        claims_registry_cls(**claims_options).validate(decoded_token.claims)
        return dict(decoded_token.claims)

    @property
    def jwks(self) -> dict[str, list[dict[str, JSONValue]]] | None:
        if self.jwk is None:
            return None
        return {"keys": [self.jwk]}


def encode_jwt(
    payload: dict[str, JSONValue],
    *,
    key: str | bytes,
    algorithm: SigningAlgorithm,
    key_id: str | None = None,
) -> str:
    headers: dict[str, str] = {"alg": algorithm}
    if key_id is not None:
        headers["kid"] = key_id
    token = jwt.encode(headers, payload, _import_key(key, algorithm))
    return token.decode("utf-8") if isinstance(token, bytes) else token


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


def _build_claims_options(
    *,
    audience: str | list[str] | None,
    issuer: str | None,
    required_claims: list[str] | None,
) -> dict[str, dict[str, object]]:
    claims_options: dict[str, dict[str, object]] = {}
    if audience is not None:
        claims_options["aud"] = {
            "essential": True,
            **({"values": audience} if isinstance(audience, list) else {"value": audience}),
        }
    if issuer is not None:
        claims_options["iss"] = {"essential": True, "value": issuer}
    for claim in required_claims or []:
        claims_options.setdefault(claim, {})["essential"] = True
    return claims_options


def _import_key(key: str | bytes, algorithm: SigningAlgorithm) -> OctKey | RSAKey:
    if algorithm == "HS256":
        return OctKey.import_key(key)
    return RSAKey.import_key(key)


def _rsa_public_jwk(public_key: rsa.RSAPublicKey, key_id: str) -> dict[str, str]:
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
