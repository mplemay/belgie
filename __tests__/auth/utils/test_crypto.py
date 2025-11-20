from uuid import UUID

from brugge.auth.utils.crypto import generate_session_id, generate_state_token


def test_generate_state_token_returns_string() -> None:
    token = generate_state_token()
    assert isinstance(token, str)


def test_generate_state_token_is_not_empty() -> None:
    token = generate_state_token()
    assert len(token) > 0


def test_generate_state_token_is_url_safe() -> None:
    token = generate_state_token()
    # URL-safe tokens should only contain alphanumeric, -, and _
    assert all(c.isalnum() or c in "-_" for c in token)


def test_generate_state_token_is_unique() -> None:
    token1 = generate_state_token()
    token2 = generate_state_token()
    assert token1 != token2


def test_generate_state_token_has_sufficient_length() -> None:
    token = generate_state_token()
    # 32 bytes in base64 should be at least 40 characters
    assert len(token) >= 40


def test_generate_state_token_multiple_unique() -> None:
    tokens = {generate_state_token() for _ in range(100)}
    assert len(tokens) == 100


def test_generate_session_id_returns_uuid() -> None:
    session_id = generate_session_id()
    assert isinstance(session_id, UUID)


def test_generate_session_id_is_unique() -> None:
    id1 = generate_session_id()
    id2 = generate_session_id()
    assert id1 != id2


def test_generate_session_id_valid_uuid4() -> None:
    session_id = generate_session_id()
    # UUID4 should have version 4
    assert session_id.version == 4


def test_generate_session_id_multiple_unique() -> None:
    ids = {generate_session_id() for _ in range(100)}
    assert len(ids) == 100


def test_generate_session_id_can_convert_to_string() -> None:
    session_id = generate_session_id()
    str_id = str(session_id)
    assert isinstance(str_id, str)
    assert len(str_id) == 36  # Standard UUID string format
