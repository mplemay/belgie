from __future__ import annotations

import time

from belgie_oauth_server.query_signature import (
    build_signed_oauth_query,
    make_signature,
    parse_verified_oauth_query,
    verify_oauth_query_params,
)

_TO_SIGN = "response_type=code&client_id=abc&redirect_uri=https%3A%2F%2Fclient.example%2Fcb&state=xyz&exp=2000000000"
_EXPECTED_SIG = "Q6ZBzqnvf75y8TNKP3e0PSeYSSHBVnOqEgwkPpJQd+w="


def test_make_signature_matches_node_btoa() -> None:
    assert make_signature(_TO_SIGN, "test-secret-belgie") == _EXPECTED_SIG


def test_verify_oauth_query_params_accepts_constructed_query() -> None:
    full = f"{_TO_SIGN}&sig={_EXPECTED_SIG.replace('+', '%2B')}"
    assert verify_oauth_query_params(full, "test-secret-belgie") is True


def test_verify_rejects_tamper() -> None:
    full = f"{_TO_SIGN}&sig={_EXPECTED_SIG.replace('+', '%2B')}"
    bad = full.replace("state=xyz", "state=evil")
    assert verify_oauth_query_params(bad, "test-secret-belgie") is False


def test_verify_rejects_expired() -> None:
    old = "response_type=code&client_id=a&redirect_uri=https%3A%2F%2Fc&state=s&exp=1"
    signed = f"{old}&sig={make_signature(old, 's')}"
    assert verify_oauth_query_params(signed, "s") is False


def test_build_and_verify_roundtrip(monkeypatch: object) -> None:
    secret = "roundtrip-secret"  # noqa: S105
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
    q = build_signed_oauth_query(
        {
            "response_type": "code",
            "client_id": "c1",
            "redirect_uri": "https://a.example/cb",
            "state": "s1",
            "scope": "openid profile",
        },
        secret=secret,
        code_expires_in_seconds=600,
    )
    assert verify_oauth_query_params(q, secret) is True
    parsed = parse_verified_oauth_query(q, secret)
    assert parsed is not None
    assert parsed.get("client_id") == "c1"
    assert parsed.get("state") == "s1"
    assert parsed.get("exp") is not None
    assert "sig" not in parsed
