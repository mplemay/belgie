from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class UserProtocol(Protocol):
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class AccountProtocol(Protocol):
    id: UUID
    user_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    token_type: str | None
    scope: str | None
    id_token: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class SessionProtocol(Protocol):
    id: UUID
    user_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime


@runtime_checkable
class OAuthStateProtocol(Protocol):
    id: UUID
    state: str
    code_verifier: str | None
    redirect_url: str | None
    created_at: datetime
    expires_at: datetime
