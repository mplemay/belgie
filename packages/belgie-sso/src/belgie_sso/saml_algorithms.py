from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

type DeprecatedAlgorithmBehavior = Literal["warn", "allow", "reject"]

SIGNATURE_ALGORITHM_URIS = {
    "rsa-sha1": "http://www.w3.org/2000/09/xmldsig#rsa-sha1",
    "rsa-sha256": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
    "rsa-sha384": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha384",
    "rsa-sha512": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha512",
    "ecdsa-sha256": "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256",
    "ecdsa-sha384": "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha384",
    "ecdsa-sha512": "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha512",
}
SIGNATURE_ALGORITHMS_BY_URI = {value: key for key, value in SIGNATURE_ALGORITHM_URIS.items()}
DIGEST_ALGORITHM_URIS = {
    "sha1": "http://www.w3.org/2000/09/xmldsig#sha1",
    "sha256": "http://www.w3.org/2001/04/xmlenc#sha256",
    "sha384": "http://www.w3.org/2001/04/xmldsig-more#sha384",
    "sha512": "http://www.w3.org/2001/04/xmlenc#sha512",
}
DIGEST_ALGORITHMS_BY_URI = {value: key for key, value in DIGEST_ALGORITHM_URIS.items()}
KEY_ENCRYPTION_ALGORITHM_URIS = {
    "rsa-1_5": "http://www.w3.org/2001/04/xmlenc#rsa-1_5",
    "rsa-oaep": "http://www.w3.org/2001/04/xmlenc#rsa-oaep-mgf1p",
    "rsa-oaep-sha256": "http://www.w3.org/2009/xmlenc11#rsa-oaep",
}
KEY_ENCRYPTION_ALGORITHMS_BY_URI = {value: key for key, value in KEY_ENCRYPTION_ALGORITHM_URIS.items()}
DATA_ENCRYPTION_ALGORITHM_URIS = {
    "tripledes-cbc": "http://www.w3.org/2001/04/xmlenc#tripledes-cbc",
    "aes128-cbc": "http://www.w3.org/2001/04/xmlenc#aes128-cbc",
    "aes192-cbc": "http://www.w3.org/2001/04/xmlenc#aes192-cbc",
    "aes256-cbc": "http://www.w3.org/2001/04/xmlenc#aes256-cbc",
    "aes128-gcm": "http://www.w3.org/2009/xmlenc11#aes128-gcm",
    "aes192-gcm": "http://www.w3.org/2009/xmlenc11#aes192-gcm",
    "aes256-gcm": "http://www.w3.org/2009/xmlenc11#aes256-gcm",
}
DATA_ENCRYPTION_ALGORITHMS_BY_URI = {value: key for key, value in DATA_ENCRYPTION_ALGORITHM_URIS.items()}

SECURE_SIGNATURE_ALGORITHMS = frozenset(
    {
        "rsa-sha256",
        "rsa-sha384",
        "rsa-sha512",
        "ecdsa-sha256",
        "ecdsa-sha384",
        "ecdsa-sha512",
    },
)
DEPRECATED_SIGNATURE_ALGORITHMS = frozenset({"rsa-sha1"})
SECURE_DIGEST_ALGORITHMS = frozenset({"sha256", "sha384", "sha512"})
DEPRECATED_DIGEST_ALGORITHMS = frozenset({"sha1"})
DEPRECATED_KEY_ENCRYPTION_ALGORITHMS = frozenset({"rsa-1_5"})
DEPRECATED_DATA_ENCRYPTION_ALGORITHMS = frozenset({"tripledes-cbc"})

_SHORT_SIGNATURE_ALGORITHMS = {
    "sha1": "rsa-sha1",
    "sha256": "rsa-sha256",
    "sha384": "rsa-sha384",
    "sha512": "rsa-sha512",
}


@dataclass(slots=True, frozen=True)
class _AlgorithmValidationPolicy:
    allowed_algorithms: tuple[str, ...] | None
    deprecated_algorithms: frozenset[str]
    secure_algorithms: frozenset[str] | None
    on_deprecated: DeprecatedAlgorithmBehavior


def normalize_signature_algorithm(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        msg = "signature_algorithm must be a non-empty string"
        raise ValueError(msg)
    if normalized in SIGNATURE_ALGORITHM_URIS:
        return normalized
    if normalized in SIGNATURE_ALGORITHMS_BY_URI:
        return SIGNATURE_ALGORITHMS_BY_URI[normalized]
    if normalized in _SHORT_SIGNATURE_ALGORITHMS:
        return _SHORT_SIGNATURE_ALGORITHMS[normalized]
    msg = f"SAML signature algorithm not recognized: {value}"
    raise ValueError(msg)


def normalize_digest_algorithm(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        msg = "digest_algorithm must be a non-empty string"
        raise ValueError(msg)
    if normalized in DIGEST_ALGORITHM_URIS:
        return normalized
    if normalized in DIGEST_ALGORITHMS_BY_URI:
        return DIGEST_ALGORITHMS_BY_URI[normalized]
    msg = f"SAML digest algorithm not recognized: {value}"
    raise ValueError(msg)


def normalize_key_encryption_algorithm(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        msg = "SAML key encryption algorithm must be a non-empty string"
        raise ValueError(msg)
    if normalized in KEY_ENCRYPTION_ALGORITHM_URIS:
        return normalized
    if normalized in KEY_ENCRYPTION_ALGORITHMS_BY_URI:
        return KEY_ENCRYPTION_ALGORITHMS_BY_URI[normalized]
    msg = f"SAML key encryption algorithm not recognized: {value}"
    raise ValueError(msg)


def normalize_data_encryption_algorithm(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        msg = "SAML data encryption algorithm must be a non-empty string"
        raise ValueError(msg)
    if normalized in DATA_ENCRYPTION_ALGORITHM_URIS:
        return normalized
    if normalized in DATA_ENCRYPTION_ALGORITHMS_BY_URI:
        return DATA_ENCRYPTION_ALGORITHMS_BY_URI[normalized]
    msg = f"SAML data encryption algorithm not recognized: {value}"
    raise ValueError(msg)


def normalize_signature_allowlist(values: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(dict.fromkeys(normalize_signature_algorithm(value) for value in values))


def normalize_digest_allowlist(values: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(dict.fromkeys(normalize_digest_algorithm(value) for value in values))


def normalize_key_encryption_allowlist(values: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(dict.fromkeys(normalize_key_encryption_algorithm(value) for value in values))


def normalize_data_encryption_allowlist(values: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(dict.fromkeys(normalize_data_encryption_algorithm(value) for value in values))


def validate_config_signature_algorithm(
    algorithm: str,
    *,
    on_deprecated: DeprecatedAlgorithmBehavior,
    allowed_signature_algorithms: tuple[str, ...] | None,
) -> str:
    normalized = normalize_signature_algorithm(algorithm)
    _validate_algorithm(
        algorithm=normalized,
        policy=_AlgorithmValidationPolicy(
            allowed_algorithms=allowed_signature_algorithms,
            deprecated_algorithms=DEPRECATED_SIGNATURE_ALGORITHMS,
            secure_algorithms=SECURE_SIGNATURE_ALGORITHMS,
            on_deprecated=on_deprecated,
        ),
        deprecated_message=(
            f"SAML config uses deprecated signature algorithm: {algorithm}. Consider using SHA-256 or stronger."
        ),
        allowlist_message=f"SAML signature algorithm not in allow-list: {algorithm}",
        unknown_message=f"SAML signature algorithm not recognized: {algorithm}",
    )
    return normalized


def validate_config_digest_algorithm(
    algorithm: str,
    *,
    on_deprecated: DeprecatedAlgorithmBehavior,
    allowed_digest_algorithms: tuple[str, ...] | None,
) -> str:
    normalized = normalize_digest_algorithm(algorithm)
    _validate_algorithm(
        algorithm=normalized,
        policy=_AlgorithmValidationPolicy(
            allowed_algorithms=allowed_digest_algorithms,
            deprecated_algorithms=DEPRECATED_DIGEST_ALGORITHMS,
            secure_algorithms=SECURE_DIGEST_ALGORITHMS,
            on_deprecated=on_deprecated,
        ),
        deprecated_message=(
            f"SAML config uses deprecated digest algorithm: {algorithm}. Consider using SHA-256 or stronger."
        ),
        allowlist_message=f"SAML digest algorithm not in allow-list: {algorithm}",
        unknown_message=f"SAML digest algorithm not recognized: {algorithm}",
    )
    return normalized


def validate_runtime_signature_algorithm(
    algorithm: str,
    *,
    on_deprecated: DeprecatedAlgorithmBehavior,
    allowed_signature_algorithms: tuple[str, ...] | None,
) -> None:
    _validate_algorithm(
        algorithm=normalize_signature_algorithm(algorithm),
        policy=_AlgorithmValidationPolicy(
            allowed_algorithms=allowed_signature_algorithms,
            deprecated_algorithms=DEPRECATED_SIGNATURE_ALGORITHMS,
            secure_algorithms=SECURE_SIGNATURE_ALGORITHMS,
            on_deprecated=on_deprecated,
        ),
        deprecated_message=(
            f"SAML response uses deprecated signature algorithm: {algorithm}. "
            "Please configure your IdP to use SHA-256 or stronger."
        ),
        allowlist_message=f"SAML signature algorithm not in allow-list: {algorithm}",
        unknown_message=f"SAML signature algorithm not recognized: {algorithm}",
    )


def validate_runtime_digest_algorithm(
    algorithm: str,
    *,
    on_deprecated: DeprecatedAlgorithmBehavior,
    allowed_digest_algorithms: tuple[str, ...] | None,
) -> None:
    _validate_algorithm(
        algorithm=normalize_digest_algorithm(algorithm),
        policy=_AlgorithmValidationPolicy(
            allowed_algorithms=allowed_digest_algorithms,
            deprecated_algorithms=DEPRECATED_DIGEST_ALGORITHMS,
            secure_algorithms=SECURE_DIGEST_ALGORITHMS,
            on_deprecated=on_deprecated,
        ),
        deprecated_message=(
            f"SAML response uses deprecated digest algorithm: {algorithm}. "
            "Please configure your IdP to use SHA-256 or stronger."
        ),
        allowlist_message=f"SAML digest algorithm not in allow-list: {algorithm}",
        unknown_message=f"SAML digest algorithm not recognized: {algorithm}",
    )


def validate_runtime_key_encryption_algorithm(
    algorithm: str,
    *,
    on_deprecated: DeprecatedAlgorithmBehavior,
    allowed_key_encryption_algorithms: tuple[str, ...] | None,
) -> None:
    _validate_algorithm(
        algorithm=normalize_key_encryption_algorithm(algorithm),
        policy=_AlgorithmValidationPolicy(
            allowed_algorithms=allowed_key_encryption_algorithms,
            deprecated_algorithms=DEPRECATED_KEY_ENCRYPTION_ALGORITHMS,
            secure_algorithms=None,
            on_deprecated=on_deprecated,
        ),
        deprecated_message=(
            f"SAML response uses deprecated key encryption algorithm: {algorithm}. "
            "Please configure your IdP to use RSA-OAEP."
        ),
        allowlist_message=f"SAML key encryption algorithm not in allow-list: {algorithm}",
        unknown_message=f"SAML key encryption algorithm not recognized: {algorithm}",
    )


def validate_runtime_data_encryption_algorithm(
    algorithm: str,
    *,
    on_deprecated: DeprecatedAlgorithmBehavior,
    allowed_data_encryption_algorithms: tuple[str, ...] | None,
) -> None:
    _validate_algorithm(
        algorithm=normalize_data_encryption_algorithm(algorithm),
        policy=_AlgorithmValidationPolicy(
            allowed_algorithms=allowed_data_encryption_algorithms,
            deprecated_algorithms=DEPRECATED_DATA_ENCRYPTION_ALGORITHMS,
            secure_algorithms=None,
            on_deprecated=on_deprecated,
        ),
        deprecated_message=(
            f"SAML response uses deprecated data encryption algorithm: {algorithm}. "
            "Please configure your IdP to use AES-GCM."
        ),
        allowlist_message=f"SAML data encryption algorithm not in allow-list: {algorithm}",
        unknown_message=f"SAML data encryption algorithm not recognized: {algorithm}",
    )


def _validate_algorithm(
    *,
    algorithm: str,
    policy: _AlgorithmValidationPolicy,
    deprecated_message: str,
    allowlist_message: str,
    unknown_message: str,
) -> None:
    if policy.allowed_algorithms is not None:
        if algorithm not in policy.allowed_algorithms:
            raise ValueError(allowlist_message)
        return

    if algorithm in policy.deprecated_algorithms:
        _handle_deprecated_algorithm(message=deprecated_message, behavior=policy.on_deprecated)
        return

    if policy.secure_algorithms is None:
        return
    if algorithm not in policy.secure_algorithms:
        raise ValueError(unknown_message)


def _handle_deprecated_algorithm(*, message: str, behavior: DeprecatedAlgorithmBehavior) -> None:
    if behavior == "reject":
        raise ValueError(message)
    if behavior == "warn":
        warnings.warn(message, RuntimeWarning, stacklevel=3)
