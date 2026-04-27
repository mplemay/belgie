from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from belgie_core.core.exceptions import OAuthError

from belgie_oauth._helpers import coerce_optional_str, normalize_datetime

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.oauth_account import OAuthAccountProtocol
    from belgie_proto.core.oauth_state import OAuthStateProtocol

    from belgie_oauth._types import (
        JSONValue,
        OAuthFlowIntent,
        OAuthSameSite,
        RawProfile,
        ResponseCookiePayload,
        TokenResponsePayload,
    )


def _coerce_expiration(value: JSONValue | datetime) -> datetime | None:
    if isinstance(value, datetime):
        return normalize_datetime(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _resolve_expiration(
    token: TokenResponsePayload,
    *,
    absolute_keys: tuple[str, ...],
    relative_keys: tuple[str, ...],
) -> datetime | None:
    for key in absolute_keys:
        if resolved := _coerce_expiration(token.get(key)):
            return resolved
    for key in relative_keys:
        if isinstance(seconds_until_expiry := token.get(key), (int, float)):
            return datetime.now(UTC) + timedelta(seconds=int(seconds_until_expiry))
    return None


def parse_oauth_flow_intent(
    value: JSONValue,
    *,
    default: OAuthFlowIntent = "signin",
) -> OAuthFlowIntent:
    if value == "signin":
        return "signin"
    if value == "link":
        return "link"
    return default


def parse_oauth_samesite(
    value: JSONValue,
    *,
    default: OAuthSameSite = "lax",
) -> OAuthSameSite:
    if value == "lax":
        return "lax"
    if value == "strict":
        return "strict"
    if value == "none":
        return "none"
    return default


@dataclass(slots=True, frozen=True, kw_only=True)
class OAuthTokenSet:
    access_token: str | None
    token_type: str | None
    refresh_token: str | None
    scope: str | None
    id_token: str | None
    access_token_expires_at: datetime | None
    refresh_token_expires_at: datetime | None
    raw: TokenResponsePayload = field(default_factory=dict)

    @classmethod
    def from_response(
        cls,
        token: TokenResponsePayload,
        *,
        existing: OAuthTokenSet | OAuthLinkedAccount | None = None,
        require_access_token: bool = True,
    ) -> OAuthTokenSet:
        access_token = coerce_optional_str(token.get("access_token"))
        if access_token is None and existing is not None:
            access_token = existing.access_token
        if access_token is None and require_access_token:
            msg = "missing required field in token response: access_token"
            raise OAuthError(msg)

        access_token_expires_at = _resolve_expiration(
            token,
            absolute_keys=("expires_at", "access_token_expires_at"),
            relative_keys=("expires_in", "access_token_expires_in"),
        )
        refresh_token_expires_at = _resolve_expiration(
            token,
            absolute_keys=("refresh_token_expires_at",),
            relative_keys=("refresh_token_expires_in", "refresh_expires_in"),
        )

        if existing is not None:
            if access_token_expires_at is None:
                access_token_expires_at = existing.access_token_expires_at
            if refresh_token_expires_at is None:
                refresh_token_expires_at = existing.refresh_token_expires_at

        return cls(
            access_token=access_token,
            token_type=coerce_optional_str(token.get("token_type"))
            or (existing.token_type if existing is not None else None),
            refresh_token=coerce_optional_str(token.get("refresh_token"))
            or (existing.refresh_token if existing is not None else None),
            scope=coerce_optional_str(token.get("scope")) or (existing.scope if existing is not None else None),
            id_token=coerce_optional_str(token.get("id_token"))
            or (existing.id_token if existing is not None else None),
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
            raw=dict(token),
        )

    @classmethod
    def from_id_token(  # noqa: PLR0913
        cls,
        *,
        id_token: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_type: str | None = None,
        scope: str | None = None,
        access_token_expires_at: datetime | None = None,
        refresh_token_expires_at: datetime | None = None,
    ) -> OAuthTokenSet:
        raw: TokenResponsePayload = {"id_token": id_token}
        if access_token is not None:
            raw["access_token"] = access_token
        if refresh_token is not None:
            raw["refresh_token"] = refresh_token
        if token_type is not None:
            raw["token_type"] = token_type
        if scope is not None:
            raw["scope"] = scope
        if access_token_expires_at is not None:
            raw["expires_at"] = int(access_token_expires_at.timestamp())
        if refresh_token_expires_at is not None:
            raw["refresh_token_expires_at"] = int(refresh_token_expires_at.timestamp())
        return cls(
            access_token=access_token,
            token_type=token_type,
            refresh_token=refresh_token,
            scope=scope,
            id_token=id_token,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
            raw=raw,
        )

    @classmethod
    def from_account(cls, account: OAuthLinkedAccount) -> OAuthTokenSet:
        raw: TokenResponsePayload = {}
        if account.access_token is not None:
            raw["access_token"] = account.access_token
        if account.refresh_token is not None:
            raw["refresh_token"] = account.refresh_token
        if account.token_type is not None:
            raw["token_type"] = account.token_type
        if account.scope is not None:
            raw["scope"] = account.scope
        if account.id_token is not None:
            raw["id_token"] = account.id_token
        if account.access_token_expires_at is not None:
            raw["expires_at"] = int(account.access_token_expires_at.timestamp())
        if account.refresh_token_expires_at is not None:
            raw["refresh_token_expires_at"] = int(account.refresh_token_expires_at.timestamp())
        return cls(
            access_token=account.access_token,
            token_type=account.token_type,
            refresh_token=account.refresh_token,
            scope=account.scope,
            id_token=account.id_token,
            access_token_expires_at=account.access_token_expires_at,
            refresh_token_expires_at=account.refresh_token_expires_at,
            raw=raw,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class OAuthUserInfo:
    provider_account_id: str
    email: str | None
    email_verified: bool
    name: str | None = None
    image: str | None = None
    raw: RawProfile = field(default_factory=dict)


@dataclass(slots=True, frozen=True, kw_only=True)
class OAuthLinkedAccount:
    id: UUID
    individual_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    access_token_expires_at: datetime | None
    refresh_token_expires_at: datetime | None
    token_type: str | None
    scope: str | None
    id_token: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(
        cls,
        account: OAuthAccountProtocol,
        *,
        access_token: str | None,
        refresh_token: str | None,
        id_token: str | None,
    ) -> OAuthLinkedAccount:
        return cls(
            id=account.id,
            individual_id=account.individual_id,
            provider=account.provider,
            provider_account_id=account.provider_account_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=normalize_datetime(account.access_token_expires_at),
            refresh_token_expires_at=normalize_datetime(account.refresh_token_expires_at),
            token_type=account.token_type,
            scope=account.scope,
            id_token=id_token,
            created_at=normalize_datetime(account.created_at) or datetime.now(UTC),
            updated_at=normalize_datetime(account.updated_at) or datetime.now(UTC),
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class PendingOAuthState:
    state: str
    provider: str
    individual_id: UUID | None
    code_verifier: str | None
    nonce: str | None
    intent: OAuthFlowIntent
    redirect_url: str | None
    error_redirect_url: str | None
    new_user_redirect_url: str | None
    payload: JSONValue
    request_sign_up: bool
    expires_at: datetime


@dataclass(slots=True, frozen=True, kw_only=True)
class ConsumedOAuthState:
    state: str
    provider: str | None
    individual_id: UUID | None
    code_verifier: str | None
    nonce: str | None
    intent: OAuthFlowIntent
    redirect_url: str | None
    error_redirect_url: str | None
    new_user_redirect_url: str | None
    payload: JSONValue
    request_sign_up: bool
    expires_at: datetime

    @classmethod
    def from_model(cls, oauth_state: OAuthStateProtocol) -> ConsumedOAuthState:
        return cls(
            state=oauth_state.state,
            provider=oauth_state.provider,
            individual_id=oauth_state.individual_id,
            code_verifier=oauth_state.code_verifier,
            nonce=oauth_state.nonce,
            intent=oauth_state.intent,
            redirect_url=oauth_state.redirect_url,
            error_redirect_url=oauth_state.error_redirect_url,
            new_user_redirect_url=oauth_state.new_user_redirect_url,
            payload=oauth_state.payload,
            request_sign_up=oauth_state.request_sign_up,
            expires_at=normalize_datetime(oauth_state.expires_at) or datetime.now(UTC),
        )

    @classmethod
    def from_pending(cls, oauth_state: PendingOAuthState) -> ConsumedOAuthState:
        return cls(
            state=oauth_state.state,
            provider=oauth_state.provider,
            individual_id=oauth_state.individual_id,
            code_verifier=oauth_state.code_verifier,
            nonce=oauth_state.nonce,
            intent=oauth_state.intent,
            redirect_url=oauth_state.redirect_url,
            error_redirect_url=oauth_state.error_redirect_url,
            new_user_redirect_url=oauth_state.new_user_redirect_url,
            payload=oauth_state.payload,
            request_sign_up=oauth_state.request_sign_up,
            expires_at=oauth_state.expires_at,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class ResponseCookie:
    name: str
    value: str
    max_age: int
    path: str = "/"
    httponly: bool = True
    secure: bool = True
    samesite: OAuthSameSite = "lax"
    domain: str | None = None

    def to_dict(self) -> ResponseCookiePayload:
        return {
            "name": self.name,
            "value": self.value,
            "max_age": self.max_age,
            "path": self.path,
            "httponly": self.httponly,
            "secure": self.secure,
            "samesite": self.samesite,
            "domain": self.domain,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, JSONValue]) -> ResponseCookie:
        max_age_value = payload["max_age"]
        if isinstance(max_age_value, bool) or not isinstance(max_age_value, (int, float, str)):
            msg = "invalid OAuth cookie payload: max_age"
            raise OAuthError(msg)
        return cls(
            name=str(payload["name"]),
            value=str(payload["value"]),
            max_age=int(max_age_value),
            path=coerce_optional_str(payload.get("path")) or "/",
            httponly=bool(payload.get("httponly", True)),
            secure=bool(payload.get("secure", True)),
            samesite=parse_oauth_samesite(payload.get("samesite")),
            domain=coerce_optional_str(payload.get("domain")),
        )
