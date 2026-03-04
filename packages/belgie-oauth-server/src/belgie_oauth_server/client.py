from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, Request

from belgie_oauth_server.provider import SimpleOAuthProvider
from belgie_oauth_server.utils import construct_redirect_uri, join_url

type OAuthLoginIntent = Literal["login", "create"]


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthLoginContext:
    state: str
    intent: OAuthLoginIntent
    prompt: str | None
    return_to: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthServerClient:
    provider: SimpleOAuthProvider
    issuer_url: str

    async def resolve_login_context(self, request: Request) -> OAuthLoginContext:
        state = request.query_params.get("state")
        if state is None and (return_to := request.query_params.get("return_to")) is not None:
            query = parse_qs(urlparse(return_to).query)
            state_values = query.get("state")
            if state_values:
                state = state_values[0]

        if not state:
            raise HTTPException(status_code=400, detail="missing state")

        state_data = await self.provider.load_authorization_state(state)
        if state_data is None:
            raise HTTPException(status_code=400, detail="Invalid state parameter")

        return_to_base = join_url(self.issuer_url, "login/callback")
        return_to_url = construct_redirect_uri(return_to_base, state=state)

        return OAuthLoginContext(
            state=state,
            intent=state_data.intent,
            prompt=state_data.prompt,
            return_to=return_to_url,
        )
