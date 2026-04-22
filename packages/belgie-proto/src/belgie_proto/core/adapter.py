from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from belgie_proto.core.account import AccountAdapterProtocol, AccountProtocol
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_account import OAuthAccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Any, Literal
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


@runtime_checkable
class AdapterProtocol[
    IndividualT: IndividualProtocol,
    OAuthAccountT: OAuthAccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
](AccountAdapterProtocol[AccountProtocol], Protocol):
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

    async def create_oauth_account(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> OAuthAccountT: ...

    async def get_oauth_account(
        self,
        session: DBConnection,
        provider: str,
        provider_account_id: str,
    ) -> OAuthAccountT | None: ...

    async def get_oauth_account_by_id(
        self,
        session: DBConnection,
        oauth_account_id: UUID,
    ) -> OAuthAccountT | None: ...

    async def get_oauth_account_by_individual_and_provider(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
    ) -> OAuthAccountT | None: ...

    async def get_oauth_account_by_individual_provider_account_id(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> OAuthAccountT | None: ...

    async def list_oauth_accounts(
        self,
        session: DBConnection,
        individual_id: UUID,
        *,
        provider: str | None = None,
    ) -> list[OAuthAccountT]: ...

    async def update_oauth_account(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
        **tokens: Any,  # noqa: ANN401
    ) -> OAuthAccountT | None: ...

    async def update_oauth_account_by_id(
        self,
        session: DBConnection,
        oauth_account_id: UUID,
        **tokens: Any,  # noqa: ANN401
    ) -> OAuthAccountT | None: ...

    async def delete_oauth_account(
        self,
        session: DBConnection,
        oauth_account_id: UUID,
    ) -> bool: ...

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
        provider: str | None = None,
        code_verifier: str | None = None,
        nonce: str | None = None,
        intent: Literal["signin", "link"] = "signin",
        redirect_url: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: Any | None = None,  # noqa: ANN401
        request_sign_up: bool = False,  # noqa: FBT001, FBT002
        individual_id: UUID | None = None,
    ) -> OAuthStateT: ...

    async def get_oauth_state(
        self,
        session: DBConnection,
        state: str,
    ) -> OAuthStateT | None: ...

    async def delete_oauth_state(self, session: DBConnection, state: str) -> bool: ...

    async def delete_individual(self, session: DBConnection, individual_id: UUID) -> bool: ...
