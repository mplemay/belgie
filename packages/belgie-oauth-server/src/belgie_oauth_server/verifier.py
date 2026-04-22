from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from belgie_oauth_server.provider import AccessToken, SimpleOAuthProvider  # noqa: TC001

JWT_DELIMITER_COUNT = 2


@dataclass(frozen=True, slots=True)
class VerifiedAccessToken:
    source: Literal["jwt", "stored"]
    token: AccessToken


async def verify_local_access_token(
    provider: SimpleOAuthProvider,
    token: str,
    *,
    audience: str | list[str] | None = None,
    verify_exp: bool = True,
) -> VerifiedAccessToken | None:
    looks_like_jwt = token.count(".") == JWT_DELIMITER_COUNT
    if (
        signed_token := provider.verify_signed_access_token(
            token,
            audience=audience,
            verify_exp=verify_exp,
        )
    ) is not None:
        if await provider.load_access_token(token) is None:
            return None
        return VerifiedAccessToken(source="jwt", token=signed_token)

    if audience is not None and looks_like_jwt:
        return None

    if (stored_token := await provider.load_access_token(token)) is not None:
        return VerifiedAccessToken(source="stored", token=stored_token)

    return None
