from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from belgie_core.core.exceptions import InvalidStateError

from belgie_oauth._helpers import SecretBox, coerce_optional_str, normalize_datetime
from belgie_oauth._models import ConsumedOAuthState, PendingOAuthState, ResponseCookie, parse_oauth_flow_intent

if TYPE_CHECKING:
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import CookieSettings
    from fastapi import Request, Response

    from belgie_oauth._types import CookieStoredOAuthStatePayload, OAuthStateMarkerPayload, OAuthStateStrategy


def _cookie_name(*, provider_id: str, suffix: str) -> str:
    return f"belgie_oauth_{provider_id}_{suffix}"


def _uuid_from_string(value: str | None) -> UUID | None:
    if not value:
        return None
    return UUID(value)


class OAuthStateStore(ABC):
    def __init__(
        self,
        *,
        provider_id: str,
        cookie_settings: CookieSettings,
        secret: str,
    ) -> None:
        self.provider_id = provider_id
        self.cookie_settings = cookie_settings
        self._box = SecretBox(secret=secret, label="oauth state")

    @abstractmethod
    async def create_authorization_state(
        self,
        client: BelgieClient,
        oauth_state: PendingOAuthState,
    ) -> list[ResponseCookie]: ...

    @abstractmethod
    async def consume_callback_state(
        self,
        client: BelgieClient,
        request: Request,
        state: str,
    ) -> ConsumedOAuthState: ...

    @abstractmethod
    def has_callback_cookie(self, request: Request) -> bool: ...

    @abstractmethod
    def clear_cookies(self, response: Response) -> None: ...

    def _response_cookie(self, *, name: str, value: str, expires_at: datetime) -> ResponseCookie:
        max_age = max(int((expires_at - datetime.now(UTC)).total_seconds()), 0)
        return ResponseCookie(
            name=name,
            value=value,
            max_age=max_age,
            httponly=True,
            secure=self.cookie_settings.secure,
            samesite=self.cookie_settings.same_site,
            domain=self.cookie_settings.domain,
        )

    def _delete_cookie(self, response: Response, name: str) -> None:
        response.delete_cookie(
            key=name,
            path="/",
            secure=self.cookie_settings.secure,
            httponly=True,
            samesite=self.cookie_settings.same_site,
            domain=self.cookie_settings.domain,
        )


class AdapterOAuthStateStore(OAuthStateStore):
    def __init__(self, *, provider_id: str, cookie_settings: CookieSettings, secret: str) -> None:
        super().__init__(provider_id=provider_id, cookie_settings=cookie_settings, secret=secret)
        self._marker_cookie_name = _cookie_name(provider_id=provider_id, suffix="state_marker")

    async def create_authorization_state(
        self,
        client: BelgieClient,
        oauth_state: PendingOAuthState,
    ) -> list[ResponseCookie]:
        await client.adapter.create_oauth_state(
            client.db,
            state=oauth_state.state,
            expires_at=oauth_state.expires_at.replace(tzinfo=None),
            provider=oauth_state.provider,
            code_verifier=oauth_state.code_verifier,
            nonce=oauth_state.nonce,
            intent=oauth_state.intent,
            redirect_url=oauth_state.redirect_url,
            error_redirect_url=oauth_state.error_redirect_url,
            new_user_redirect_url=oauth_state.new_user_redirect_url,
            payload=oauth_state.payload,
            request_sign_up=oauth_state.request_sign_up,
            individual_id=oauth_state.individual_id,
        )
        marker_payload: OAuthStateMarkerPayload = {
            "state": oauth_state.state,
            "provider": oauth_state.provider,
            "expires_at": oauth_state.expires_at.isoformat(),
        }
        marker = self._box.encode(marker_payload)
        return [
            self._response_cookie(
                name=self._marker_cookie_name,
                value=marker,
                expires_at=oauth_state.expires_at,
            ),
        ]

    async def consume_callback_state(
        self,
        client: BelgieClient,
        request: Request,
        state: str,
    ) -> ConsumedOAuthState:
        oauth_state = await client.adapter.get_oauth_state(client.db, state)
        if oauth_state is None:
            msg = "Invalid OAuth state"
            raise InvalidStateError(msg)

        marker_token = request.cookies.get(self._marker_cookie_name)
        if marker_token is None:
            msg = "missing OAuth state marker"
            raise InvalidStateError(msg)

        payload = self._box.decode(marker_token, error_message="invalid OAuth state marker")
        if payload.get("state") != state or payload.get("provider") != self.provider_id:
            msg = "OAuth state marker mismatch"
            raise InvalidStateError(msg)

        if (expires_at_value := coerce_optional_str(payload.get("expires_at"))) is None:
            msg = "missing OAuth state marker expiration"
            raise InvalidStateError(msg)
        marker_expires_at = normalize_datetime(datetime.fromisoformat(expires_at_value))
        if marker_expires_at is None or marker_expires_at <= datetime.now(UTC):
            msg = "OAuth state expired"
            raise InvalidStateError(msg)

        consumed_state = ConsumedOAuthState.from_model(oauth_state)
        if consumed_state.expires_at <= datetime.now(UTC):
            await client.adapter.delete_oauth_state(client.db, state)
            msg = "OAuth state expired"
            raise InvalidStateError(msg)

        await client.adapter.delete_oauth_state(client.db, state)
        return consumed_state

    def has_callback_cookie(self, request: Request) -> bool:
        return request.cookies.get(self._marker_cookie_name) is not None

    def clear_cookies(self, response: Response) -> None:
        self._delete_cookie(response, self._marker_cookie_name)


class CookieOAuthStateStore(OAuthStateStore):
    def __init__(self, *, provider_id: str, cookie_settings: CookieSettings, secret: str) -> None:
        super().__init__(provider_id=provider_id, cookie_settings=cookie_settings, secret=secret)
        self._state_cookie_name = _cookie_name(provider_id=provider_id, suffix="state")

    async def create_authorization_state(
        self,
        client: BelgieClient,  # noqa: ARG002
        oauth_state: PendingOAuthState,
    ) -> list[ResponseCookie]:
        cookie_payload: CookieStoredOAuthStatePayload = {
            "state": oauth_state.state,
            "provider": oauth_state.provider,
            "individual_id": str(oauth_state.individual_id) if oauth_state.individual_id else None,
            "code_verifier": oauth_state.code_verifier,
            "nonce": oauth_state.nonce,
            "intent": oauth_state.intent,
            "redirect_url": oauth_state.redirect_url,
            "error_redirect_url": oauth_state.error_redirect_url,
            "new_user_redirect_url": oauth_state.new_user_redirect_url,
            "payload": oauth_state.payload,
            "request_sign_up": oauth_state.request_sign_up,
            "expires_at": oauth_state.expires_at.isoformat(),
        }
        payload = self._box.encode(cookie_payload)
        return [
            self._response_cookie(
                name=self._state_cookie_name,
                value=payload,
                expires_at=oauth_state.expires_at,
            ),
        ]

    async def consume_callback_state(
        self,
        client: BelgieClient,  # noqa: ARG002
        request: Request,
        state: str,
    ) -> ConsumedOAuthState:
        cookie_value = request.cookies.get(self._state_cookie_name)
        if cookie_value is None:
            msg = "missing OAuth state cookie"
            raise InvalidStateError(msg)

        payload = self._box.decode(cookie_value, error_message="invalid OAuth state cookie")
        if payload.get("state") != state or payload.get("provider") != self.provider_id:
            msg = "OAuth state mismatch"
            raise InvalidStateError(msg)

        if (expires_at_value := coerce_optional_str(payload.get("expires_at"))) is None:
            msg = "missing OAuth state expiration"
            raise InvalidStateError(msg)
        expires_at = normalize_datetime(datetime.fromisoformat(expires_at_value))
        if expires_at is None or expires_at <= datetime.now(UTC):
            msg = "OAuth state expired"
            raise InvalidStateError(msg)

        return ConsumedOAuthState(
            state=state,
            provider=coerce_optional_str(payload.get("provider")),
            individual_id=_uuid_from_string(coerce_optional_str(payload.get("individual_id"))),
            code_verifier=coerce_optional_str(payload.get("code_verifier")),
            nonce=coerce_optional_str(payload.get("nonce")),
            intent=parse_oauth_flow_intent(payload.get("intent")),
            redirect_url=coerce_optional_str(payload.get("redirect_url")),
            error_redirect_url=coerce_optional_str(payload.get("error_redirect_url")),
            new_user_redirect_url=coerce_optional_str(payload.get("new_user_redirect_url")),
            payload=payload.get("payload"),
            request_sign_up=bool(payload.get("request_sign_up", False)),
            expires_at=expires_at,
        )

    def has_callback_cookie(self, request: Request) -> bool:
        return request.cookies.get(self._state_cookie_name) is not None

    def clear_cookies(self, response: Response) -> None:
        self._delete_cookie(response, self._state_cookie_name)


def build_state_store(
    *,
    provider_id: str,
    strategy: OAuthStateStrategy,
    cookie_settings: CookieSettings,
    secret: str,
) -> OAuthStateStore:
    if strategy == "cookie":
        return CookieOAuthStateStore(
            provider_id=provider_id,
            cookie_settings=cookie_settings,
            secret=secret,
        )
    return AdapterOAuthStateStore(
        provider_id=provider_id,
        cookie_settings=cookie_settings,
        secret=secret,
    )
