from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from belgie_proto.account import AccountProtocol
from belgie_proto.oauth_state import OAuthStateProtocol
from belgie_proto.session import SessionProtocol
from belgie_proto.user import UserProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.connection import DBConnection


@runtime_checkable
class AdapterProtocol[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](Protocol):
    """Protocol for database adapters."""

    @property
    def dependency(self) -> Callable[[], DBConnection | AsyncGenerator[DBConnection, None]]: ...

    async def create_user(
        self,
        session: DBConnection,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified: bool = False,
    ) -> UserT: ...

    async def get_user_by_id(self, session: DBConnection, user_id: UUID) -> UserT | None: ...

    async def get_user_by_email(self, session: DBConnection, email: str) -> UserT | None: ...

    async def update_user(
        self,
        session: DBConnection,
        user_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> UserT | None: ...

    async def create_account(
        self,
        session: DBConnection,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT: ...

    async def get_account(
        self,
        session: DBConnection,
        provider: str,
        provider_account_id: str,
    ) -> AccountT | None: ...

    async def get_account_by_user_and_provider(
        self,
        session: DBConnection,
        user_id: UUID,
        provider: str,
    ) -> AccountT | None: ...

    async def update_account(
        self,
        session: DBConnection,
        user_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT | None: ...

    async def create_session(
        self,
        session: DBConnection,
        user_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT: ...

    async def get_session(
        self,
        session: DBConnection,
        session_id: UUID,
    ) -> SessionT | None: ...

    async def update_session(
        self,
        session: DBConnection,
        session_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> SessionT | None: ...

    async def delete_session(self, session: DBConnection, session_id: UUID) -> bool: ...

    async def delete_expired_sessions(self, session: DBConnection) -> int: ...

    async def create_oauth_state(
        self,
        session: DBConnection,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None,
    ) -> OAuthStateT: ...

    async def get_oauth_state(
        self,
        session: DBConnection,
        state: str,
    ) -> OAuthStateT | None: ...

    async def delete_oauth_state(self, session: DBConnection, state: str) -> bool: ...

    async def delete_user(self, session: DBConnection, user_id: UUID) -> bool: ...
