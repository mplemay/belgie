from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from belgie_proto.core import AdapterProtocol
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_account import OAuthAccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from fastapi import HTTPException, Request, Response, status
from fastapi.security import SecurityScopes

from belgie_core.core.settings import CookieSettings
from belgie_core.session.manager import SessionManager
from belgie_core.utils.scopes import validate_scopes

if TYPE_CHECKING:
    from belgie_proto.core.individual import IndividualProtocol


type AfterSignUpCallback[IndividualT: IndividualProtocol] = Callable[..., Awaitable[None]]


@dataclass(frozen=True, slots=True, kw_only=True)
class BelgieClient[
    IndividualT: IndividualProtocol,
    OAuthAccountT: OAuthAccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
]:
    """Client for authentication operations with injected database session.

    This class provides authentication methods with a captured database session,
    allowing for convenient auth operations without explicitly passing db to each method.

    Typically obtained via Belgie.__call__() as a FastAPI dependency:
        client: Annotated[BelgieClient, Depends(belgie)]

    Type Parameters:
        IndividualT: Individual model type implementing IndividualProtocol
        OAuthAccountT: OAuthAccount model type implementing OAuthAccountProtocol
        SessionT: Session model type implementing SessionProtocol
        OAuthStateT: OAuth state model type implementing OAuthStateProtocol

    Attributes:
        db: Captured database connection
        adapter: Database adapter for persistence operations
        session_manager: Session manager for session lifecycle operations
        cookie_settings: Settings for the session cookie

    Example:
        >>> @app.delete("/account")
        >>> async def delete_account(
        ...     client: Annotated[BelgieClient, Depends(belgie)],
        ...     request: Request,
        ... ):
        ...     individual = await client.get_individual(SecurityScopes(), request)
        ...     await client.delete_individual(individual)
        ...     return {"message": "OAuthAccount deleted"}
    """

    db: DBConnection
    adapter: AdapterProtocol[IndividualT, OAuthAccountT, SessionT, OAuthStateT]
    session_manager: SessionManager[IndividualT, OAuthAccountT, SessionT, OAuthStateT]
    cookie_settings: CookieSettings = field(default_factory=CookieSettings)
    after_sign_up: AfterSignUpCallback[IndividualT] | None = None

    async def _get_session_from_cookie(self, request: Request) -> SessionT | None:
        """Extract and validate session from request cookies.

        Args:
            request: FastAPI Request object containing cookies

        Returns:
            Valid session object or None if cookie missing/invalid/expired
        """
        if not (session_id_str := request.cookies.get(self.cookie_settings.name)):
            return None

        try:
            session_id = UUID(session_id_str)
        except ValueError:
            return None

        return await self.session_manager.get_session(self.db, session_id)

    async def get_individual(self, security_scopes: SecurityScopes, request: Request) -> IndividualT:
        """Get the authenticated individual from the request session.

        Extracts the session from cookies, validates it, and returns the authenticated individual.
        Optionally validates individual-level scopes if specified.

        Args:
            security_scopes: FastAPI SecurityScopes for scope validation
            request: FastAPI Request object containing cookies

        Returns:
            Authenticated individual object

        Raises:
            HTTPException: 401 if not authenticated or session invalid
            HTTPException: 403 if required scopes are not granted

        Example:
            >>> individual = await client.get_individual(SecurityScopes(scopes=["read"]), request)
            >>> print(individual.email)
        """
        if not (session := await self._get_session_from_cookie(request)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        if not (individual := await self.adapter.get_individual_by_id(self.db, session.individual_id)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="individual not found",
            )

        if security_scopes.scopes and not validate_scopes(individual.scopes, security_scopes.scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return individual

    async def get_session(self, request: Request) -> SessionT:
        """Get the current session from the request.

        Extracts and validates the session from cookies.

        Args:
            request: FastAPI Request object containing cookies

        Returns:
            Active session object

        Raises:
            HTTPException: 401 if not authenticated or session invalid/expired

        Example:
            >>> session = await client.get_session(request)
            >>> print(session.expires_at)
        """
        if not (session := await self._get_session_from_cookie(request)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        return session

    async def delete_individual(self, individual: IndividualT) -> bool:
        """Delete an individual and all associated data."""
        return await self.adapter.delete_individual(self.db, individual.id)

    async def get_individual_from_session(self, session_id: UUID) -> IndividualT | None:
        """Retrieve an individual from a session ID.

        Args:
            session_id: UUID of the session

        Returns:
            Individual object if session is valid and exists, None otherwise

        Example:
            >>> from uuid import UUID
            >>> session_id = UUID("...")
            >>> individual = await client.get_individual_from_session(session_id)
            >>> if individual:
            ...     print(f"Found individual: {individual.email}")
        """
        if not (session := await self.session_manager.get_session(self.db, session_id)):
            return None

        return await self.adapter.get_individual_by_id(self.db, session.individual_id)

    async def get_or_create_individual(
        self,
        email: str,
        *,
        name: str | None = None,
        image: str | None = None,
        email_verified_at: datetime | None = None,
    ) -> tuple[IndividualT, bool]:
        if individual := await self.adapter.get_individual_by_email(self.db, email):
            return individual, False

        individual = await self.adapter.create_individual(
            self.db,
            email=email,
            name=name,
            image=image,
            email_verified_at=email_verified_at,
        )
        return individual, True

    async def upsert_oauth_account(
        self,
        *,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: Any,  # noqa: ANN401
    ) -> OAuthAccountT:
        if (
            await self.adapter.get_oauth_account_by_individual_and_provider(
                self.db,
                individual_id,
                provider,
            )
            and (
                account := await self.adapter.update_oauth_account(
                    self.db,
                    individual_id=individual_id,
                    provider=provider,
                    **tokens,
                )
            )
            is not None
        ):
            return account

        return await self.adapter.create_oauth_account(
            self.db,
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
            **tokens,
        )

    async def sign_in_individual(
        self,
        individual: IndividualT,
        *,
        request: Request | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionT:
        if request:
            if ip_address is None and request.client:
                ip_address = request.client.host
            if user_agent is None:
                user_agent = request.headers.get("user-agent")

        return await self.session_manager.create_session(
            self.db,
            individual_id=individual.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def sign_up(  # noqa: PLR0913
        self,
        email: str,
        *,
        request: Request | None = None,
        name: str | None = None,
        image: str | None = None,
        email_verified_at: datetime | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[IndividualT, SessionT]:
        individual, created = await self.get_or_create_individual(
            email,
            name=name,
            image=image,
            email_verified_at=email_verified_at,
        )
        session = await self.sign_in_individual(
            individual,
            request=request,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if created and self.after_sign_up is not None:
            await self.after_sign_up(
                client=self,
                request=request,
                individual=individual,
            )
        return individual, session

    def create_session_cookie[R: Response](self, session: SessionT, response: R) -> R:
        response.set_cookie(
            key=self.cookie_settings.name,
            value=str(session.id),
            max_age=self.session_manager.max_age,
            httponly=self.cookie_settings.http_only,
            secure=self.cookie_settings.secure,
            samesite=self.cookie_settings.same_site,
            domain=self.cookie_settings.domain,
        )
        return response

    async def sign_out(self, session_id: UUID) -> bool:
        """Sign out an individual by deleting their session.

        Args:
            session_id: UUID of the session to delete

        Returns:
            True if session was deleted, False if session didn't exist

        Example:
            >>> session = await client.get_session(request)
            >>> await client.sign_out(session.id)
        """
        if await self.session_manager.get_session(self.db, session_id) is None:
            return False

        return await self.session_manager.delete_session(self.db, session_id)
