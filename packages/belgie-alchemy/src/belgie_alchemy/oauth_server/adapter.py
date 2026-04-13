from __future__ import annotations

# ruff: noqa: PLR0913, A002
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.oauth_server import OAuthServerAdapterProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.oauth_server.access_token import OAuthAccessTokenProtocol
    from belgie_proto.oauth_server.client import OAuthClientProtocol
    from belgie_proto.oauth_server.code import OAuthAuthorizationCodeProtocol
    from belgie_proto.oauth_server.consent import OAuthConsentProtocol
    from belgie_proto.oauth_server.refresh_token import OAuthRefreshTokenProtocol
    from belgie_proto.oauth_server.state import OAuthAuthorizationStateProtocol
    from belgie_proto.oauth_server.types import (
        AuthorizationIntent,
        OAuthAudience,
        OAuthClientType,
        OAuthSubjectType,
        TokenEndpointAuthMethod,
    )


class OAuthServerAdapter[
    ClientT: OAuthClientProtocol,
    AuthorizationStateT: OAuthAuthorizationStateProtocol,
    AuthorizationCodeT: OAuthAuthorizationCodeProtocol,
    AccessTokenT: OAuthAccessTokenProtocol,
    RefreshTokenT: OAuthRefreshTokenProtocol,
    ConsentT: OAuthConsentProtocol,
](
    OAuthServerAdapterProtocol[
        ClientT,
        AuthorizationStateT,
        AuthorizationCodeT,
        AccessTokenT,
        RefreshTokenT,
        ConsentT,
    ],
):
    def __init__(
        self,
        *,
        oauth_client: type[ClientT],
        oauth_authorization_state: type[AuthorizationStateT],
        oauth_authorization_code: type[AuthorizationCodeT],
        oauth_access_token: type[AccessTokenT],
        oauth_refresh_token: type[RefreshTokenT],
        oauth_consent: type[ConsentT],
    ) -> None:
        self.oauth_client_model = oauth_client
        self.oauth_authorization_state_model = oauth_authorization_state
        self.oauth_authorization_code_model = oauth_authorization_code
        self.oauth_access_token_model = oauth_access_token
        self.oauth_refresh_token_model = oauth_refresh_token
        self.oauth_consent_model = oauth_consent

    async def _commit_and_refresh(self, session: DBConnection, instance: object) -> object:
        try:
            await session.commit()
            await session.refresh(instance)
        except Exception:
            await session.rollback()
            raise
        return instance

    async def create_client(
        self,
        session: DBConnection,
        *,
        client_id: str,
        client_secret_hash: str | None,
        redirect_uris: list[str],
        post_logout_redirect_uris: list[str] | None,
        token_endpoint_auth_method: TokenEndpointAuthMethod,
        grant_types: list[str],
        response_types: list[str],
        scope: str | None,
        client_name: str | None,
        client_uri: str | None,
        logo_uri: str | None,
        contacts: list[str] | None,
        tos_uri: str | None,
        policy_uri: str | None,
        jwks_uri: str | None,
        jwks: dict[str, str] | dict[str, object] | None,
        software_id: str | None,
        software_version: str | None,
        software_statement: str | None,
        type: OAuthClientType | None,
        subject_type: OAuthSubjectType | None,
        require_pkce: bool | None,
        enable_end_session: bool | None,
        client_id_issued_at: int | None,
        client_secret_expires_at: int | None,
        individual_id: UUID | None,
    ) -> ClientT:
        client = self.oauth_client_model(
            client_id=client_id,
            client_secret_hash=client_secret_hash,
            redirect_uris=redirect_uris,
            post_logout_redirect_uris=post_logout_redirect_uris,
            token_endpoint_auth_method=token_endpoint_auth_method,
            grant_types=grant_types,
            response_types=response_types,
            scope=scope,
            client_name=client_name,
            client_uri=client_uri,
            logo_uri=logo_uri,
            contacts=contacts,
            tos_uri=tos_uri,
            policy_uri=policy_uri,
            jwks_uri=jwks_uri,
            jwks=jwks,
            software_id=software_id,
            software_version=software_version,
            software_statement=software_statement,
            type=type,
            subject_type=subject_type,
            require_pkce=require_pkce,
            enable_end_session=enable_end_session,
            client_id_issued_at=client_id_issued_at,
            client_secret_expires_at=client_secret_expires_at,
            individual_id=individual_id,
        )
        session.add(client)
        return await self._commit_and_refresh(session, client)  # type: ignore[return-value]

    async def get_client_by_client_id(self, session: DBConnection, *, client_id: str) -> ClientT | None:
        stmt = select(self.oauth_client_model).where(self.oauth_client_model.client_id == client_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
        client_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        code_challenge: str | None,
        resource: str | None,
        scopes: list[str] | None,
        nonce: str | None,
        prompt: str | None,
        intent: AuthorizationIntent,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> AuthorizationStateT:
        authorization_state = self.oauth_authorization_state_model(
            state=state,
            client_id=client_id,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
            code_challenge=code_challenge,
            resource=resource,
            scopes=scopes,
            nonce=nonce,
            prompt=prompt,
            intent=intent,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        session.add(authorization_state)
        return await self._commit_and_refresh(session, authorization_state)  # type: ignore[return-value]

    async def get_authorization_state(self, session: DBConnection, *, state: str) -> AuthorizationStateT | None:
        stmt = select(self.oauth_authorization_state_model).where(self.oauth_authorization_state_model.state == state)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def bind_authorization_state(
        self,
        session: DBConnection,
        *,
        state: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> AuthorizationStateT | None:
        authorization_state = await self.get_authorization_state(session, state=state)
        if authorization_state is None:
            return None
        authorization_state.individual_id = individual_id
        authorization_state.session_id = session_id
        authorization_state.updated_at = datetime.now(UTC)
        return await self._commit_and_refresh(session, authorization_state)  # type: ignore[return-value]

    async def update_authorization_state_interaction(
        self,
        session: DBConnection,
        *,
        state: str,
        prompt: str | None,
        intent: AuthorizationIntent,
        scopes: list[str] | None,
    ) -> AuthorizationStateT | None:
        authorization_state = await self.get_authorization_state(session, state=state)
        if authorization_state is None:
            return None
        authorization_state.prompt = prompt
        authorization_state.intent = intent
        if scopes is not None:
            authorization_state.scopes = scopes
        authorization_state.updated_at = datetime.now(UTC)
        return await self._commit_and_refresh(session, authorization_state)  # type: ignore[return-value]

    async def delete_authorization_state(self, session: DBConnection, *, state: str) -> bool:
        stmt = delete(self.oauth_authorization_state_model).where(self.oauth_authorization_state_model.state == state)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_authorization_code(
        self,
        session: DBConnection,
        *,
        code_hash: str,
        client_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        code_challenge: str | None,
        scopes: list[str],
        resource: str | None,
        nonce: str | None,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> AuthorizationCodeT:
        authorization_code = self.oauth_authorization_code_model(
            code_hash=code_hash,
            client_id=client_id,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
            code_challenge=code_challenge,
            scopes=scopes,
            resource=resource,
            nonce=nonce,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        session.add(authorization_code)
        return await self._commit_and_refresh(session, authorization_code)  # type: ignore[return-value]

    async def get_authorization_code_by_code_hash(
        self,
        session: DBConnection,
        *,
        code_hash: str,
    ) -> AuthorizationCodeT | None:
        stmt = select(self.oauth_authorization_code_model).where(
            self.oauth_authorization_code_model.code_hash == code_hash,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_authorization_code_by_code_hash(self, session: DBConnection, *, code_hash: str) -> bool:
        stmt = delete(self.oauth_authorization_code_model).where(
            self.oauth_authorization_code_model.code_hash == code_hash,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_access_token(
        self,
        session: DBConnection,
        *,
        token_hash: str,
        client_id: str,
        scopes: list[str],
        resource: OAuthAudience | None,
        refresh_token_id: UUID | None,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> AccessTokenT:
        access_token = self.oauth_access_token_model(
            token_hash=token_hash,
            client_id=client_id,
            scopes=scopes,
            resource=resource,
            refresh_token_id=refresh_token_id,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        session.add(access_token)
        return await self._commit_and_refresh(session, access_token)  # type: ignore[return-value]

    async def get_access_token_by_token_hash(self, session: DBConnection, *, token_hash: str) -> AccessTokenT | None:
        stmt = select(self.oauth_access_token_model).where(self.oauth_access_token_model.token_hash == token_hash)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_access_token_by_token_hash(self, session: DBConnection, *, token_hash: str) -> bool:
        stmt = delete(self.oauth_access_token_model).where(self.oauth_access_token_model.token_hash == token_hash)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def delete_access_tokens_by_refresh_token_id(self, session: DBConnection, *, refresh_token_id: UUID) -> int:
        stmt = delete(self.oauth_access_token_model).where(
            self.oauth_access_token_model.refresh_token_id == refresh_token_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount  # type: ignore[attr-defined]

    async def delete_access_tokens_for_client_and_individual(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
    ) -> int:
        stmt = delete(self.oauth_access_token_model).where(
            self.oauth_access_token_model.client_id == client_id,
            self.oauth_access_token_model.individual_id == individual_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount  # type: ignore[attr-defined]

    async def delete_access_tokens_for_client_individual_and_session(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> int:
        stmt = delete(self.oauth_access_token_model).where(
            self.oauth_access_token_model.client_id == client_id,
            self.oauth_access_token_model.individual_id == individual_id,
            self.oauth_access_token_model.session_id == session_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount  # type: ignore[attr-defined]

    async def create_refresh_token(
        self,
        session: DBConnection,
        *,
        token_hash: str,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        individual_id: UUID | None,
        session_id: UUID | None,
        expires_at: datetime,
    ) -> RefreshTokenT:
        refresh_token = self.oauth_refresh_token_model(
            token_hash=token_hash,
            client_id=client_id,
            scopes=scopes,
            resource=resource,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        session.add(refresh_token)
        return await self._commit_and_refresh(session, refresh_token)  # type: ignore[return-value]

    async def get_refresh_token_by_token_hash(self, session: DBConnection, *, token_hash: str) -> RefreshTokenT | None:
        stmt = select(self.oauth_refresh_token_model).where(self.oauth_refresh_token_model.token_hash == token_hash)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_refresh_token_revoked_at(
        self,
        session: DBConnection,
        *,
        refresh_token_id: UUID,
        revoked_at: datetime,
    ) -> RefreshTokenT | None:
        stmt = select(self.oauth_refresh_token_model).where(self.oauth_refresh_token_model.id == refresh_token_id)
        result = await session.execute(stmt)
        refresh_token = result.scalar_one_or_none()
        if refresh_token is None:
            return None
        refresh_token.revoked_at = revoked_at
        refresh_token.updated_at = datetime.now(UTC)
        return await self._commit_and_refresh(session, refresh_token)  # type: ignore[return-value]

    async def delete_refresh_token_by_token_hash(self, session: DBConnection, *, token_hash: str) -> bool:
        stmt = delete(self.oauth_refresh_token_model).where(self.oauth_refresh_token_model.token_hash == token_hash)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def delete_refresh_tokens_for_client_and_individual(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
    ) -> int:
        stmt = delete(self.oauth_refresh_token_model).where(
            self.oauth_refresh_token_model.client_id == client_id,
            self.oauth_refresh_token_model.individual_id == individual_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount  # type: ignore[attr-defined]

    async def delete_refresh_tokens_for_client_individual_and_session(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        session_id: UUID,
    ) -> int:
        stmt = delete(self.oauth_refresh_token_model).where(
            self.oauth_refresh_token_model.client_id == client_id,
            self.oauth_refresh_token_model.individual_id == individual_id,
            self.oauth_refresh_token_model.session_id == session_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount  # type: ignore[attr-defined]

    async def upsert_consent(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
        scopes: list[str],
    ) -> ConsentT:
        consent = await self.get_consent(session, client_id=client_id, individual_id=individual_id)
        if consent is None:
            consent = self.oauth_consent_model(
                client_id=client_id,
                individual_id=individual_id,
                scopes=scopes,
            )
            session.add(consent)
            return await self._commit_and_refresh(session, consent)  # type: ignore[return-value]

        consent.scopes = scopes
        consent.updated_at = datetime.now(UTC)
        return await self._commit_and_refresh(session, consent)  # type: ignore[return-value]

    async def get_consent(
        self,
        session: DBConnection,
        *,
        client_id: str,
        individual_id: UUID,
    ) -> ConsentT | None:
        stmt = select(self.oauth_consent_model).where(
            self.oauth_consent_model.client_id == client_id,
            self.oauth_consent_model.individual_id == individual_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
