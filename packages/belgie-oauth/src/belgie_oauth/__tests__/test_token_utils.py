import pytest
from belgie_oauth.token_utils import apply_prefix, hash_token, strip_prefix


def test_hash_token_deterministic() -> None:
    secret = "secret"  # noqa: S105
    token = "token"  # noqa: S105
    first = hash_token(token, secret)
    second = hash_token(token, secret)
    assert first == second
    assert first != token


def test_apply_and_strip_prefix() -> None:
    token = "token"  # noqa: S105
    prefixed = apply_prefix(token, "pre_")
    assert prefixed == "pre_token"
    assert strip_prefix(prefixed, "pre_") == token


def test_strip_prefix_raises() -> None:
    with pytest.raises(ValueError, match="expected prefix"):
        strip_prefix("token", "pre_")
