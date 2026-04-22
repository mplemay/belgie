from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, Request, status

from belgie_oauth_server.utils import construct_redirect_uri, join_url

if TYPE_CHECKING:
    from belgie_oauth_server.provider import SimpleOAuthProvider

type OAuthServerLoginIntent = Literal["login", "create", "consent", "select_account", "post_login"]


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthServerLoginContext:
    state: str
    intent: OAuthServerLoginIntent
    prompt: str | None
    return_to: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthLoginFlowClient:
    provider: SimpleOAuthProvider
    issuer_url: str

    async def try_resolve_login_context(self, request: Request) -> OAuthServerLoginContext | None:
        state = request.query_params.get("state")
        if state is None and (return_to := request.query_params.get("return_to")) is not None:
            query = parse_qs(urlparse(return_to).query)
            state_values = query.get("state")
            if state_values:
                state = state_values[0]

        if state is None:
            return None
        if not state:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter")

        state_data = await self.provider.load_authorization_state(state)
        if state_data is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter")

        return_to_url = _build_return_to_url(self.issuer_url, state, state_data.intent)

        return OAuthServerLoginContext(
            state=state,
            intent=state_data.intent,
            prompt=state_data.prompt,
            return_to=return_to_url,
        )

    async def resolve_login_context(self, request: Request) -> OAuthServerLoginContext:
        context = await self.try_resolve_login_context(request)
        if context is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state")
        return context


def _build_return_to_url(issuer_url: str, state: str, intent: OAuthServerLoginIntent) -> str:
    if intent == "create":
        return construct_redirect_uri(join_url(issuer_url, "oauth2/continue"), state=state, created="true")
    if intent == "select_account":
        return construct_redirect_uri(join_url(issuer_url, "oauth2/continue"), state=state, selected="true")
    if intent == "post_login":
        return construct_redirect_uri(join_url(issuer_url, "oauth2/continue"), state=state, post_login="true")
    if intent == "consent":
        return construct_redirect_uri(join_url(issuer_url, "oauth2/consent"), state=state)
    return construct_redirect_uri(join_url(issuer_url, "oauth2/login/callback"), state=state)
