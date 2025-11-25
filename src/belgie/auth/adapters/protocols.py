from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class UserProtocol[S: str](Protocol):
    # Generic over scope type S (must be str or subclass like StrEnum)
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[S] | None  # User's application-level scopes (None means no scopes)


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


class AdapterProtocol[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](Protocol):
    """Protocol for database adapters."""

    async def create_user(
        self,
        db: AsyncSession,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified: bool = False,
    ) -> UserT: ...

    async def get_user_by_id(self, db: AsyncSession, user_id: UUID) -> UserT | None: ...

    async def get_user_by_email(self, db: AsyncSession, email: str) -> UserT | None: ...

    async def update_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> UserT | None: ...

    async def create_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT: ...

    async def get_account(
        self,
        db: AsyncSession,
        provider: str,
        provider_account_id: str,
    ) -> AccountT | None: ...

    async def get_account_by_user_and_provider(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
    ) -> AccountT | None: ...

    async def update_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT | None: ...

    async def create_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT: ...

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> SessionT | None: ...

    async def update_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> SessionT | None: ...

    async def delete_session(self, db: AsyncSession, session_id: UUID) -> bool: ...

    async def delete_expired_sessions(self, db: AsyncSession) -> int: ...

    async def create_oauth_state(
        self,
        db: AsyncSession,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None,
    ) -> OAuthStateT: ...

    async def get_oauth_state(
        self,
        db: AsyncSession,
        state: str,
    ) -> OAuthStateT | None: ...

    async def delete_oauth_state(self, db: AsyncSession, state: str) -> bool: ...

    async def delete_user(self, db: AsyncSession, user_id: UUID) -> bool: ...

    @property
    def dependency(self) -> Callable[[], Any]: ...
