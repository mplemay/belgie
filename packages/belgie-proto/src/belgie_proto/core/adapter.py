from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from belgie_proto.core.account import AccountProtocol
from belgie_proto.core.customer import CustomerAdapterProtocol, CustomerProtocol
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


@runtime_checkable
class AdapterProtocol[
    IndividualT: IndividualProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](CustomerAdapterProtocol[CustomerProtocol], Protocol):
    """Protocol for database adapters."""

    async def create_individual(
        self,
        session: DBConnection,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified_at: datetime | None = None,
    ) -> IndividualT: ...

    async def get_individual_by_id(self, session: DBConnection, individual_id: UUID) -> IndividualT | None: ...

    async def get_individual_by_email(self, session: DBConnection, email: str) -> IndividualT | None: ...

    async def update_individual(
        self,
        session: DBConnection,
        individual_id: UUID,
        **updates: Any,  # noqa: ANN401
    ) -> IndividualT | None: ...

    async def create_account(
        self,
        session: DBConnection,
        individual_id: UUID,
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

    async def get_account_by_individual_and_provider(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
    ) -> AccountT | None: ...

    async def update_account(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> AccountT | None: ...

    async def create_session(
        self,
        session: DBConnection,
        individual_id: UUID,
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

    async def create_oauth_state(  # noqa: PLR0913
        self,
        session: DBConnection,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        redirect_url: str | None = None,
        individual_id: UUID | None = None,
    ) -> OAuthStateT: ...

    async def get_oauth_state(
        self,
        session: DBConnection,
        state: str,
    ) -> OAuthStateT | None: ...

    async def delete_oauth_state(self, session: DBConnection, state: str) -> bool: ...

    async def delete_individual(self, session: DBConnection, individual_id: UUID) -> bool: ...
