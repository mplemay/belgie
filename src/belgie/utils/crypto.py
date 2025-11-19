import secrets
from uuid import UUID, uuid4


def generate_state_token() -> str:
    return secrets.token_urlsafe(32)


def generate_session_id() -> UUID:
    return uuid4()
