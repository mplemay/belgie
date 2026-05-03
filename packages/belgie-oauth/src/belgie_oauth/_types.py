from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, runtime_checkable

from belgie_proto.core.json import JSONObject, JSONScalar, JSONValue
from belgie_proto.core.oauth_state import OAuthFlowIntent

if TYPE_CHECKING:
    from datetime import datetime

    from belgie_core.core.client import BelgieClient
    from belgie_core.core.plugin import AuthenticatedProfile
    from belgie_core.core.settings import BelgieSettings
    from belgie_core.utils.callbacks import MaybeAwaitable
    from belgie_proto.core.individual import IndividualProtocol
    from fastapi import Request

    from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo
    from belgie_oauth._transport import AuthlibOIDCClient


type OAuthResponseMode = Literal["query", "form_post"]
type OAuthSameSite = Literal["lax", "strict", "none"]
type OAuthStateStrategy = Literal["adapter", "cookie"]
type TokenEndpointAuthMethod = Literal["client_secret_basic", "client_secret_post", "none"]
type ProviderMetadata = JSONObject
type RawProfile = JSONObject
type TokenResponsePayload = JSONObject


class ResponseCookiePayload(TypedDict):
    name: str
    value: str
    max_age: int
    path: str
    httponly: bool
    secure: bool
    samesite: OAuthSameSite
    domain: str | None


class OAuthStartPayload(TypedDict):
    authorization_url: str
    cookies: list[ResponseCookiePayload]


class OAuthStateMarkerPayload(TypedDict):
    state: str
    provider: str
    expires_at: str


class CookieStoredOAuthStatePayload(TypedDict):
    state: str
    provider: str
    individual_id: str | None
    code_verifier: str | None
    nonce: str | None
    intent: OAuthFlowIntent
    redirect_url: str | None
    error_redirect_url: str | None
    new_user_redirect_url: str | None
    payload: JSONValue
    request_sign_up: bool
    expires_at: str


class OAuthAccountCookiePayload(TypedDict):
    provider: str
    oauth_account_id: str
    individual_id: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    access_token_expires_at: str | None
    refresh_token_expires_at: str | None
    scope: str | None
    token_type: str | None
    id_token: str | None
    created_at: str
    updated_at: str


type SecretBoxPayload = (
    JSONObject | OAuthStartPayload | OAuthStateMarkerPayload | CookieStoredOAuthStatePayload | OAuthAccountCookiePayload
)


class OAuthAccountTokenUpdates(TypedDict):
    access_token: str | None
    refresh_token: str | None
    access_token_expires_at: datetime | None
    refresh_token_expires_at: datetime | None
    scope: str | None
    token_type: str | None
    id_token: str | None


if TYPE_CHECKING:
    type UserInfoFetcher = Callable[
        [AuthlibOIDCClient, OAuthTokenSet, ProviderMetadata],
        Awaitable[RawProfile | OAuthUserInfo | None],
    ]

    type TokenExchangeOverride = Callable[
        [AuthlibOIDCClient, str, dict[str, str], str | None],
        Awaitable[TokenResponsePayload],
    ]

    type TokenRefreshOverride = Callable[
        [AuthlibOIDCClient, OAuthTokenSet, dict[str, str]],
        Awaitable[TokenResponsePayload],
    ]

    type ProfileMapper = Callable[[RawProfile, OAuthTokenSet], MaybeAwaitable[OAuthUserInfo]]
else:
    type UserInfoFetcher = Callable[..., Awaitable[RawProfile | None]]
    type TokenExchangeOverride = Callable[..., Awaitable[TokenResponsePayload]]
    type TokenRefreshOverride = Callable[..., Awaitable[TokenResponsePayload]]
    type ProfileMapper = Callable[..., JSONObject]


@runtime_checkable
class OAuthBelgieRuntime(Protocol):
    settings: BelgieSettings

    def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> BelgieClient | Awaitable[BelgieClient]: ...

    async def after_authenticate(
        self,
        *,
        client: BelgieClient,
        request: Request,
        individual: IndividualProtocol[str],
        profile: AuthenticatedProfile,
    ) -> None: ...


__all__ = [
    "CookieStoredOAuthStatePayload",
    "JSONObject",
    "JSONScalar",
    "JSONValue",
    "OAuthAccountCookiePayload",
    "OAuthAccountTokenUpdates",
    "OAuthBelgieRuntime",
    "OAuthFlowIntent",
    "OAuthResponseMode",
    "OAuthSameSite",
    "OAuthStartPayload",
    "OAuthStateMarkerPayload",
    "OAuthStateStrategy",
    "ProfileMapper",
    "ProviderMetadata",
    "RawProfile",
    "ResponseCookiePayload",
    "SecretBoxPayload",
    "TokenEndpointAuthMethod",
    "TokenExchangeOverride",
    "TokenRefreshOverride",
    "TokenResponsePayload",
    "UserInfoFetcher",
]
