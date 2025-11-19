from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.adapters.alchemy import AlchemyAdapter
from belgie.core.exceptions import InvalidStateError, OAuthError
from belgie.core.settings import AuthSettings
from belgie.protocols.models import AccountProtocol, OAuthStateProtocol, SessionProtocol, UserProtocol
from belgie.providers.google import GoogleOAuthProvider, GoogleUserInfo
from belgie.session.manager import SessionManager
from belgie.utils.crypto import generate_state_token
from belgie.utils.scopes import validate_scopes


class Auth[UserT: UserProtocol, AccountT: AccountProtocol, SessionT: SessionProtocol, OAuthStateT: OAuthStateProtocol]:
    def __init__(
        self,
        settings: AuthSettings,
        adapter: AlchemyAdapter[UserT, AccountT, SessionT, OAuthStateT],
        db_dependency: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.adapter = adapter
        self.db_dependency = db_dependency

        self.session_manager = SessionManager(
            adapter=adapter,
            max_age=settings.session.max_age,
            update_age=settings.session.update_age,
        )

        self.google_provider = GoogleOAuthProvider(
            client_id=settings.google.client_id,
            client_secret=settings.google.client_secret,
            redirect_uri=settings.google.redirect_uri,
            scopes=settings.google.scopes,
        )

        self.router = self._create_router()

    def _create_router(self) -> APIRouter:
        router = APIRouter(prefix="/auth", tags=["auth"])

        async def _get_db() -> AsyncSession:
            if self.db_dependency is None:
                msg = "database dependency not configured. pass db_dependency to Auth() constructor"
                raise RuntimeError(msg)
            return await self.db_dependency()  # type: ignore[misc]

        @router.get("/signin/google")
        async def signin_google(db: AsyncSession = Depends(_get_db)) -> RedirectResponse:  # noqa: B008, FAST002
            url = await self.get_google_signin_url(db)
            return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)

        @router.get("/callback/google")
        async def callback_google(
            code: str,
            state: str,
            db: AsyncSession = Depends(_get_db),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            session, _user = await self.handle_google_callback(db, code, state)

            response = RedirectResponse(
                url=self.settings.urls.signin_redirect,
                status_code=status.HTTP_302_FOUND,
            )

            response.set_cookie(
                key=self.settings.session.cookie_name,
                value=str(session.id),
                max_age=self.settings.session.max_age,
                httponly=self.settings.cookie.http_only,
                secure=self.settings.cookie.secure,
                samesite=self.settings.cookie.same_site,
                domain=self.settings.cookie.domain,
            )

            return response

        @router.post("/signout")
        async def signout(
            request: Request,
            db: AsyncSession = Depends(_get_db),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            session_id_str = request.cookies.get(self.settings.session.cookie_name)

            if session_id_str:
                try:
                    session_id = UUID(session_id_str)
                    await self.sign_out(db, session_id)
                except ValueError:
                    pass

            response = RedirectResponse(
                url=self.settings.urls.signout_redirect,
                status_code=status.HTTP_302_FOUND,
            )

            response.delete_cookie(
                key=self.settings.session.cookie_name,
                domain=self.settings.cookie.domain,
            )

            return response

        return router

    async def get_google_signin_url(
        self,
        db: AsyncSession,
    ) -> str:
        state_token = generate_state_token()

        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        await self.adapter.create_oauth_state(
            db,
            state=state_token,
            expires_at=expires_at.replace(tzinfo=None),
        )

        return self.google_provider.generate_authorization_url(state_token)

    async def handle_google_callback(
        self,
        db: AsyncSession,
        code: str,
        state: str,
    ) -> tuple[SessionT, UserT]:
        oauth_state = await self.adapter.get_oauth_state(db, state)
        if not oauth_state:
            msg = "invalid oauth state"
            raise InvalidStateError(msg)

        await self.adapter.delete_oauth_state(db, state)

        try:
            token_data = await self.google_provider.exchange_code_for_tokens(code)
        except OAuthError as e:
            msg = f"failed to exchange code for tokens: {e}"
            raise OAuthError(msg) from e

        try:
            user_info = await self.google_provider.get_user_info(token_data["access_token"])
        except OAuthError as e:
            msg = f"failed to get user info: {e}"
            raise OAuthError(msg) from e

        user = await self._get_or_create_user(db, user_info)

        await self._create_or_update_account(
            db,
            user_id=user.id,
            provider="google",
            provider_account_id=user_info.id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=token_data.get("expires_at"),
            scope=token_data.get("scope"),
        )

        session = await self.session_manager.create_session(db, user_id=user.id)

        return session, user

    async def _get_or_create_user(
        self,
        db: AsyncSession,
        user_info: GoogleUserInfo,
    ) -> UserT:
        user = await self.adapter.get_user_by_email(db, user_info.email)
        if user:
            return user

        return await self.adapter.create_user(
            db,
            email=user_info.email,
            email_verified=user_info.verified_email,
            name=user_info.name,
            image=user_info.picture,
        )

    async def _create_or_update_account(  # noqa: PLR0913
        self,
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        provider_account_id: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime | None,
        scope: str | None,
    ) -> AccountT:
        account = await self.adapter.get_account_by_user_and_provider(db, user_id, provider)

        if account:
            updated = await self.adapter.update_account(
                db,
                user_id=user_id,
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scope=scope,
            )
            if updated is None:
                msg = "failed to update account"
                raise OAuthError(msg)
            return updated

        return await self.adapter.create_account(
            db,
            user_id=user_id,
            provider=provider,
            provider_account_id=provider_account_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=scope,
        )

    async def get_user_from_session(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> UserT | None:
        session = await self.session_manager.get_session(db, session_id)
        if not session:
            return None

        return await self.adapter.get_user_by_id(db, session.user_id)

    async def sign_out(
        self,
        db: AsyncSession,
        session_id: UUID,
    ) -> bool:
        return await self.session_manager.delete_session(db, session_id)

    async def _get_session_from_cookie(
        self,
        request: Request,
        db: AsyncSession,
    ) -> SessionT | None:
        session_id_str = request.cookies.get(self.settings.session.cookie_name)
        if not session_id_str:
            return None

        try:
            session_id = UUID(session_id_str)
        except ValueError:
            return None

        return await self.session_manager.get_session(db, session_id)

    async def user(
        self,
        security_scopes: SecurityScopes,
        request: Request,
        db: AsyncSession,
    ) -> UserT:
        session = await self._get_session_from_cookie(request, db)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        user = await self.adapter.get_user_by_id(db, session.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="user not found",
            )

        if security_scopes.scopes:
            account = await self.adapter.get_account_by_user_and_provider(db, user.id, "google")
            if not account or not account.scope:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="insufficient scopes",
                )

            user_scopes = account.scope.split(" ") if isinstance(account.scope, str) else []
            if not validate_scopes(user_scopes, security_scopes.scopes):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="insufficient scopes",
                )

        return user

    async def session(
        self,
        request: Request,
        db: AsyncSession,
    ) -> SessionT:
        session = await self._get_session_from_cookie(request, db)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )

        return session
