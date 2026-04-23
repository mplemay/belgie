from __future__ import annotations

from belgie_core.core.exceptions import OAuthError


class OAuthCallbackError(OAuthError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)
