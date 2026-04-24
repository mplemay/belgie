from __future__ import annotations

import warnings

import pytest
from belgie_sso.saml_algorithms import (
    DATA_ENCRYPTION_ALGORITHM_URIS,
    DIGEST_ALGORITHM_URIS,
    KEY_ENCRYPTION_ALGORITHM_URIS,
    SIGNATURE_ALGORITHM_URIS,
    normalize_digest_algorithm,
    normalize_signature_algorithm,
    validate_config_digest_algorithm,
    validate_config_signature_algorithm,
    validate_runtime_data_encryption_algorithm,
    validate_runtime_key_encryption_algorithm,
    validate_runtime_signature_algorithm,
)


def test_normalize_signature_algorithm_accepts_short_name_and_uri() -> None:
    assert normalize_signature_algorithm("sha256") == "rsa-sha256"
    assert normalize_signature_algorithm(SIGNATURE_ALGORITHM_URIS["rsa-sha512"]) == "rsa-sha512"


def test_normalize_digest_algorithm_accepts_uri() -> None:
    assert normalize_digest_algorithm(DIGEST_ALGORITHM_URIS["sha384"]) == "sha384"


def test_runtime_signature_validation_warns_for_deprecated_algorithms_by_default() -> None:
    with pytest.warns(RuntimeWarning, match="deprecated signature algorithm: rsa-sha1"):
        validate_runtime_signature_algorithm(
            "rsa-sha1",
            on_deprecated="warn",
            allowed_signature_algorithms=None,
        )


def test_runtime_signature_validation_can_allow_or_reject_deprecated_algorithms() -> None:
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        validate_runtime_signature_algorithm(
            "rsa-sha1",
            on_deprecated="allow",
            allowed_signature_algorithms=None,
        )
    assert recorded == []

    with pytest.raises(ValueError, match="deprecated signature algorithm: rsa-sha1"):
        validate_runtime_signature_algorithm(
            "rsa-sha1",
            on_deprecated="reject",
            allowed_signature_algorithms=None,
        )


def test_config_validation_enforces_signature_and_digest_allowlists() -> None:
    with pytest.raises(ValueError, match="signature algorithm not in allow-list"):
        validate_config_signature_algorithm(
            "rsa-sha256",
            on_deprecated="warn",
            allowed_signature_algorithms=("rsa-sha512",),
        )

    with pytest.raises(ValueError, match="digest algorithm not in allow-list"):
        validate_config_digest_algorithm(
            "sha256",
            on_deprecated="warn",
            allowed_digest_algorithms=("sha512",),
        )


def test_runtime_encryption_validation_warns_for_deprecated_algorithms_by_default() -> None:
    with pytest.warns(RuntimeWarning, match="deprecated key encryption algorithm: rsa-1_5"):
        validate_runtime_key_encryption_algorithm(
            "rsa-1_5",
            on_deprecated="warn",
            allowed_key_encryption_algorithms=None,
        )

    with pytest.warns(RuntimeWarning, match="deprecated data encryption algorithm: tripledes-cbc"):
        validate_runtime_data_encryption_algorithm(
            "tripledes-cbc",
            on_deprecated="warn",
            allowed_data_encryption_algorithms=None,
        )


def test_runtime_encryption_validation_rejects_disallowed_allowlists() -> None:
    with pytest.raises(ValueError, match="key encryption algorithm not in allow-list"):
        validate_runtime_key_encryption_algorithm(
            "rsa-oaep",
            on_deprecated="warn",
            allowed_key_encryption_algorithms=("rsa-oaep-sha256",),
        )

    with pytest.raises(ValueError, match="data encryption algorithm not in allow-list"):
        validate_runtime_data_encryption_algorithm(
            "aes256-cbc",
            on_deprecated="warn",
            allowed_data_encryption_algorithms=("aes256-gcm",),
        )


def test_algorithm_uri_constants_match_expected_saml_values() -> None:
    assert SIGNATURE_ALGORITHM_URIS["rsa-sha256"] == "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
    assert KEY_ENCRYPTION_ALGORITHM_URIS["rsa-oaep"] == "http://www.w3.org/2001/04/xmlenc#rsa-oaep-mgf1p"
    assert DATA_ENCRYPTION_ALGORITHM_URIS["aes256-gcm"] == "http://www.w3.org/2009/xmlenc11#aes256-gcm"
