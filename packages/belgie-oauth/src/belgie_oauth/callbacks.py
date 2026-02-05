from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

type ClientPrivilegesCallback = Callable[[dict[str, Any]], Awaitable[bool] | bool]
type ConsentReferenceIdCallback = Callable[[dict[str, Any]], Awaitable[str | None] | str | None]
type RedirectCallback = Callable[[dict[str, Any]], Awaitable[bool | str] | bool | str]
type CustomClaimsCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass(slots=True, kw_only=True)
class OAuthCallbacks:
    client_privileges: ClientPrivilegesCallback | None = None
    consent_reference_id: ConsentReferenceIdCallback | None = None
    select_account: RedirectCallback | None = None
    post_login: RedirectCallback | None = None
    custom_access_token_claims: CustomClaimsCallback | None = None
    custom_id_token_claims: CustomClaimsCallback | None = None
    custom_userinfo_claims: CustomClaimsCallback | None = None
