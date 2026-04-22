from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from belgie_oauth_server import VerifiedResourceAccessToken

_verified_access_token_var: ContextVar[VerifiedResourceAccessToken | None] = ContextVar(
    "belgie_mcp_verified_access_token",
    default=None,
)


def get_verified_access_token() -> VerifiedResourceAccessToken | None:
    return _verified_access_token_var.get()


def set_verified_access_token(token: VerifiedResourceAccessToken | None) -> None:
    _verified_access_token_var.set(token)
