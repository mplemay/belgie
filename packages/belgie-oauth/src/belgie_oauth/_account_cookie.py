from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from belgie_core.core.exceptions import OAuthError

from belgie_oauth._helpers import SecretBox, coerce_optional_str, normalize_datetime
from belgie_oauth._models import OAuthLinkedAccount

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings, CookieSettings
    from fastapi import Request, Response

    from belgie_oauth._types import JSONValue, OAuthAccountCookiePayload


def _account_cookie_name(provider_id: str) -> str:
    return f"belgie_oauth_{provider_id}_account"


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return normalize_datetime(datetime.fromisoformat(value))


@dataclass(slots=True)
class OAuthAccountCookieStore:
    provider_id: str
    cookie_settings: CookieSettings
    max_age: int
    _box: SecretBox

    @classmethod
    def from_settings(cls, *, provider_id: str, settings: BelgieSettings) -> OAuthAccountCookieStore:
        return cls(
            provider_id=provider_id,
            cookie_settings=settings.cookie,
            max_age=settings.session.max_age,
            _box=SecretBox(secret=settings.secret, label="oauth account cookie"),
        )

    @property
    def name(self) -> str:
        return _account_cookie_name(self.provider_id)

    def set_account(self, response: Response, account: OAuthLinkedAccount) -> None:
        payload: OAuthAccountCookiePayload = {
            "provider": account.provider,
            "oauth_account_id": str(account.id),
            "individual_id": str(account.individual_id),
            "provider_account_id": account.provider_account_id,
            "access_token": account.access_token,
            "refresh_token": account.refresh_token,
            "access_token_expires_at": _serialize_datetime(account.access_token_expires_at),
            "refresh_token_expires_at": _serialize_datetime(account.refresh_token_expires_at),
            "scope": account.scope,
            "token_type": account.token_type,
            "id_token": account.id_token,
            "created_at": account.created_at.isoformat(),
            "updated_at": account.updated_at.isoformat(),
        }
        response.set_cookie(
            key=self.name,
            value=self._box.encode(payload),
            max_age=self.max_age,
            path="/",
            httponly=True,
            secure=self.cookie_settings.secure,
            samesite=self.cookie_settings.same_site,
            domain=self.cookie_settings.domain,
        )

    def read_account(
        self,
        request: Request,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
    ) -> OAuthLinkedAccount | None:
        if (token := request.cookies.get(self.name)) is None:
            return None
        try:
            payload = self._box.decode(token, error_message="invalid OAuth account cookie")
            account = OAuthLinkedAccount(
                id=UUID(self._required(payload, "oauth_account_id")),
                individual_id=UUID(self._required(payload, "individual_id")),
                provider=self._required(payload, "provider"),
                provider_account_id=self._required(payload, "provider_account_id"),
                access_token=coerce_optional_str(payload.get("access_token")),
                refresh_token=coerce_optional_str(payload.get("refresh_token")),
                access_token_expires_at=_parse_datetime(coerce_optional_str(payload.get("access_token_expires_at"))),
                refresh_token_expires_at=_parse_datetime(
                    coerce_optional_str(payload.get("refresh_token_expires_at")),
                ),
                token_type=coerce_optional_str(payload.get("token_type")),
                scope=coerce_optional_str(payload.get("scope")),
                id_token=coerce_optional_str(payload.get("id_token")),
                created_at=_parse_datetime(self._required(payload, "created_at")) or datetime.now(UTC),
                updated_at=_parse_datetime(self._required(payload, "updated_at")) or datetime.now(UTC),
            )
        except (OAuthError, ValueError):
            return None

        if account.provider != self.provider_id or account.individual_id != individual_id:
            return None
        if provider_account_id is not None and account.provider_account_id != provider_account_id:
            return None
        return account

    def clear(self, response: Response) -> None:
        response.delete_cookie(
            key=self.name,
            path="/",
            secure=self.cookie_settings.secure,
            httponly=True,
            samesite=self.cookie_settings.same_site,
            domain=self.cookie_settings.domain,
        )

    def _required(self, payload: dict[str, JSONValue], key: str) -> str:
        if (value := coerce_optional_str(payload.get(key))) is None:
            msg = f"missing OAuth account cookie value: {key}"
            raise OAuthError(msg)
        return value
