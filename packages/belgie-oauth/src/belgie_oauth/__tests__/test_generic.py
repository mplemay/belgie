from __future__ import annotations

# ruff: noqa: A002, ARG002, FBT001, FBT002, FBT003, S105, S107, TC002
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from inspect import Signature
from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from belgie_core.core.client import BelgieClient
from belgie_core.core.exceptions import InvalidStateError, OAuthError
from belgie_core.core.plugin import AuthenticatedProfile
from belgie_core.core.settings import BelgieSettings, CookieSettings
from belgie_core.session.manager import SessionManager
from belgie_proto.core.account import AccountType
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.json import JSONValue
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from belgie_oauth import OAuthClient, OAuthLinkedAccount, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo
from belgie_oauth.__tests__.helpers import build_jwks_document, build_rsa_signing_key, issue_id_token

if TYPE_CHECKING:
    from belgie_oauth._types import (
        OAuthFlowIntent,
        OAuthResponseMode,
        OAuthStateStrategy,
        ProfileMapper,
        TokenExchangeOverride,
        TokenRefreshOverride,
        UserInfoFetcher,
    )

type AccountTokenValue = str | datetime | None
type IndividualUpdateValue = str | datetime | None
type SessionUpdateValue = str | datetime | None


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _set_async_return[T](mock: AsyncMock, value: T) -> None:
    mock.side_effect = None
    mock.return_value = value


@dataclass(slots=True, kw_only=True)
class StubDBConnection:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


@dataclass(slots=True, kw_only=True)
class StubIndividual:
    id: UUID = field(default_factory=uuid4)
    account_type: AccountType = AccountType.INDIVIDUAL
    email: str = "person@example.com"
    email_verified_at: datetime | None = None
    name: str | None = None
    image: str | None = None
    scopes: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_naive_now)
    updated_at: datetime = field(default_factory=_naive_now)


@dataclass(slots=True, kw_only=True)
class StubOAuthState:
    id: UUID = field(default_factory=uuid4)
    state: str = "test-state"
    provider: str | None = "acme"
    individual_id: UUID | None = None
    code_verifier: str | None = "test-verifier"
    nonce: str | None = "test-nonce"
    intent: OAuthFlowIntent = "signin"
    redirect_url: str | None = "/after"
    error_redirect_url: str | None = None
    new_user_redirect_url: str | None = None
    payload: JSONValue = None
    request_sign_up: bool = False
    created_at: datetime = field(default_factory=_naive_now)
    expires_at: datetime = field(default_factory=lambda: _naive_now() + timedelta(minutes=5))


@dataclass(slots=True, kw_only=True)
class StubOAuthAccount:
    id: UUID = field(default_factory=uuid4)
    individual_id: UUID = field(default_factory=uuid4)
    provider: str = "acme"
    provider_account_id: str = "provider-account-1"
    access_token: str | None = "access-token"
    refresh_token: str | None = "refresh-token"
    access_token_expires_at: datetime | None = field(default_factory=lambda: _naive_now() + timedelta(hours=1))
    refresh_token_expires_at: datetime | None = field(default_factory=lambda: _naive_now() + timedelta(days=30))
    token_type: str | None = "Bearer"
    scope: str | None = "openid email profile"
    id_token: str | None = None
    created_at: datetime = field(default_factory=_naive_now)
    updated_at: datetime = field(default_factory=_naive_now)


@dataclass(slots=True, kw_only=True)
class StubSession:
    id: UUID = field(default_factory=uuid4)
    individual_id: UUID = field(default_factory=uuid4)
    expires_at: datetime = field(default_factory=lambda: _naive_now() + timedelta(days=30))
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = field(default_factory=_naive_now)
    updated_at: datetime = field(default_factory=_naive_now)


class StubAdapter:
    def __init__(self) -> None:
        self._individuals_by_id: dict[UUID, StubIndividual] = {}
        self._individual_ids_by_email: dict[str, UUID] = {}
        self._oauth_accounts_by_id: dict[UUID, StubOAuthAccount] = {}
        self._oauth_accounts_by_provider: dict[tuple[str, str], UUID] = {}
        self._oauth_accounts_by_individual: dict[tuple[UUID, str, str], UUID] = {}
        self._oauth_states: dict[str, StubOAuthState] = {}
        self._sessions: dict[UUID, StubSession] = {}

        self.get_account_by_id_mock = AsyncMock(side_effect=self._get_account_by_id)
        self.update_account_mock = AsyncMock(side_effect=self._update_account)
        self.create_individual_mock = AsyncMock(side_effect=self._create_individual)
        self.get_individual_by_id_mock = AsyncMock(side_effect=self._get_individual_by_id)
        self.get_individual_by_email_mock = AsyncMock(side_effect=self._get_individual_by_email)
        self.update_individual_mock = AsyncMock(side_effect=self._update_individual)
        self.create_oauth_account_mock = AsyncMock(side_effect=self._create_oauth_account)
        self.get_oauth_account_mock = AsyncMock(side_effect=self._get_oauth_account)
        self.get_oauth_account_by_id_mock = AsyncMock(side_effect=self._get_oauth_account_by_id)
        self.get_oauth_account_by_individual_and_provider_mock = AsyncMock(
            side_effect=self._get_oauth_account_by_individual_and_provider,
        )
        self.get_oauth_account_by_individual_provider_account_id_mock = AsyncMock(
            side_effect=self._get_oauth_account_by_individual_provider_account_id,
        )
        self.list_oauth_accounts_mock = AsyncMock(side_effect=self._list_oauth_accounts)
        self.update_oauth_account_mock = AsyncMock(side_effect=self._update_oauth_account)
        self.update_oauth_account_by_id_mock = AsyncMock(side_effect=self._update_oauth_account_by_id)
        self.delete_oauth_account_mock = AsyncMock(side_effect=self._delete_oauth_account)
        self.create_session_mock = AsyncMock(side_effect=self._create_session)
        self.get_session_mock = AsyncMock(side_effect=self._get_session)
        self.update_session_mock = AsyncMock(side_effect=self._update_session)
        self.delete_session_mock = AsyncMock(side_effect=self._delete_session)
        self.delete_expired_sessions_mock = AsyncMock(side_effect=self._delete_expired_sessions)
        self.create_oauth_state_mock = AsyncMock(side_effect=self._create_oauth_state)
        self.get_oauth_state_mock = AsyncMock(side_effect=self._get_oauth_state)
        self.delete_oauth_state_mock = AsyncMock(side_effect=self._delete_oauth_state)
        self.delete_individual_mock = AsyncMock(side_effect=self._delete_individual)

    async def _get_account_by_id(self, _session: DBConnection, account_id: UUID) -> StubIndividual | None:
        return self._individuals_by_id.get(account_id)

    async def _update_account(
        self,
        _session: DBConnection,
        account_id: UUID,
        **updates: IndividualUpdateValue,
    ) -> StubIndividual | None:
        return await self._update_individual(_session, account_id, **updates)

    async def _create_individual(
        self,
        _session: DBConnection,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified_at: datetime | None = None,
    ) -> StubIndividual:
        individual = StubIndividual(
            email=email,
            name=name,
            image=image,
            email_verified_at=email_verified_at,
        )
        self._individuals_by_id[individual.id] = individual
        self._individual_ids_by_email[email.casefold()] = individual.id
        return individual

    async def _get_individual_by_id(self, _session: DBConnection, individual_id: UUID) -> StubIndividual | None:
        return self._individuals_by_id.get(individual_id)

    async def _get_individual_by_email(self, _session: DBConnection, email: str) -> StubIndividual | None:
        if (individual_id := self._individual_ids_by_email.get(email.casefold())) is None:
            return None
        return self._individuals_by_id.get(individual_id)

    async def _update_individual(
        self,
        _session: DBConnection,
        individual_id: UUID,
        **updates: IndividualUpdateValue,
    ) -> StubIndividual | None:
        if (individual := self._individuals_by_id.get(individual_id)) is None:
            return None
        updated = replace(individual, **updates, updated_at=_naive_now())
        self._individuals_by_id[individual_id] = updated
        self._individual_ids_by_email[updated.email.casefold()] = individual_id
        return updated

    async def _create_oauth_account(
        self,
        _session: DBConnection,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount:
        account = StubOAuthAccount(
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
            access_token=_string_or_none(tokens.get("access_token")),
            refresh_token=_string_or_none(tokens.get("refresh_token")),
            access_token_expires_at=_datetime_or_none(tokens.get("access_token_expires_at")),
            refresh_token_expires_at=_datetime_or_none(tokens.get("refresh_token_expires_at")),
            token_type=_string_or_none(tokens.get("token_type")),
            scope=_string_or_none(tokens.get("scope")),
            id_token=_string_or_none(tokens.get("id_token")),
        )
        self._store_oauth_account(account)
        return account

    async def _get_oauth_account(
        self,
        _session: DBConnection,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        if (account_id := self._oauth_accounts_by_provider.get((provider, provider_account_id))) is None:
            return None
        return self._oauth_accounts_by_id.get(account_id)

    async def _get_oauth_account_by_id(
        self,
        _session: DBConnection,
        oauth_account_id: UUID,
    ) -> StubOAuthAccount | None:
        return self._oauth_accounts_by_id.get(oauth_account_id)

    async def _get_oauth_account_by_individual_and_provider(
        self,
        _session: DBConnection,
        individual_id: UUID,
        provider: str,
    ) -> StubOAuthAccount | None:
        for (
            account_individual_id,
            account_provider,
            _provider_account_id,
        ), account_id in self._oauth_accounts_by_individual.items():
            if account_individual_id == individual_id and account_provider == provider:
                return self._oauth_accounts_by_id[account_id]
        return None

    async def _get_oauth_account_by_individual_provider_account_id(
        self,
        _session: DBConnection,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        account_key = (individual_id, provider, provider_account_id)
        if (account_id := self._oauth_accounts_by_individual.get(account_key)) is None:
            return None
        return self._oauth_accounts_by_id.get(account_id)

    async def _list_oauth_accounts(
        self,
        _session: DBConnection,
        individual_id: UUID,
        *,
        provider: str | None = None,
    ) -> list[StubOAuthAccount]:
        accounts: list[StubOAuthAccount] = []
        for (
            account_individual_id,
            account_provider,
            _provider_account_id,
        ), account_id in self._oauth_accounts_by_individual.items():
            if account_individual_id != individual_id:
                continue
            if provider is not None and account_provider != provider:
                continue
            accounts.append(self._oauth_accounts_by_id[account_id])
        return accounts

    async def _update_oauth_account(
        self,
        _session: DBConnection,
        individual_id: UUID,
        provider: str,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount | None:
        account = await self._get_oauth_account_by_individual_and_provider(_session, individual_id, provider)
        if account is None:
            return None
        return await self._update_oauth_account_by_id(_session, account.id, **tokens)

    async def _update_oauth_account_by_id(
        self,
        _session: DBConnection,
        oauth_account_id: UUID,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount | None:
        if (account := self._oauth_accounts_by_id.get(oauth_account_id)) is None:
            return None
        updated = replace(
            account,
            access_token=(
                _string_or_none(tokens.get("access_token")) if "access_token" in tokens else account.access_token
            ),
            refresh_token=(
                _string_or_none(tokens.get("refresh_token")) if "refresh_token" in tokens else account.refresh_token
            ),
            access_token_expires_at=(
                _datetime_or_none(tokens.get("access_token_expires_at"))
                if "access_token_expires_at" in tokens
                else account.access_token_expires_at
            ),
            refresh_token_expires_at=(
                _datetime_or_none(tokens.get("refresh_token_expires_at"))
                if "refresh_token_expires_at" in tokens
                else account.refresh_token_expires_at
            ),
            token_type=_string_or_none(tokens.get("token_type")) if "token_type" in tokens else account.token_type,
            scope=_string_or_none(tokens.get("scope")) if "scope" in tokens else account.scope,
            id_token=_string_or_none(tokens.get("id_token")) if "id_token" in tokens else account.id_token,
            updated_at=_naive_now(),
        )
        self._store_oauth_account(updated)
        return updated

    async def _delete_oauth_account(self, _session: DBConnection, oauth_account_id: UUID) -> bool:
        if (account := self._oauth_accounts_by_id.pop(oauth_account_id, None)) is None:
            return False
        self._oauth_accounts_by_provider.pop((account.provider, account.provider_account_id), None)
        self._oauth_accounts_by_individual.pop(
            (account.individual_id, account.provider, account.provider_account_id),
            None,
        )
        return True

    async def _create_session(
        self,
        _session: DBConnection,
        individual_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StubSession:
        session = StubSession(
            individual_id=individual_id,
            expires_at=expires_at.replace(tzinfo=None),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._sessions[session.id] = session
        return session

    async def _get_session(self, _session: DBConnection, session_id: UUID) -> StubSession | None:
        return self._sessions.get(session_id)

    async def _update_session(
        self,
        _session: DBConnection,
        session_id: UUID,
        **updates: SessionUpdateValue,
    ) -> StubSession | None:
        if (session := self._sessions.get(session_id)) is None:
            return None
        updated = replace(
            session,
            expires_at=_datetime_or_none(updates.get("expires_at")) if "expires_at" in updates else session.expires_at,
            ip_address=_string_or_none(updates.get("ip_address")) if "ip_address" in updates else session.ip_address,
            user_agent=_string_or_none(updates.get("user_agent")) if "user_agent" in updates else session.user_agent,
            updated_at=_naive_now(),
        )
        self._sessions[session_id] = updated
        return updated

    async def _delete_session(self, _session: DBConnection, session_id: UUID) -> bool:
        return self._sessions.pop(session_id, None) is not None

    async def _delete_expired_sessions(self, _session: DBConnection) -> int:
        return 0

    async def _create_oauth_state(
        self,
        _session: DBConnection,
        state: str,
        expires_at: datetime,
        provider: str | None = None,
        code_verifier: str | None = None,
        nonce: str | None = None,
        intent: OAuthFlowIntent = "signin",
        redirect_url: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: JSONValue = None,
        request_sign_up: bool = False,
        individual_id: UUID | None = None,
    ) -> StubOAuthState:
        oauth_state = StubOAuthState(
            state=state,
            provider=provider,
            individual_id=individual_id,
            code_verifier=code_verifier,
            nonce=nonce,
            intent=intent,
            redirect_url=redirect_url,
            error_redirect_url=error_redirect_url,
            new_user_redirect_url=new_user_redirect_url,
            payload=payload,
            request_sign_up=request_sign_up,
            expires_at=expires_at,
        )
        self._oauth_states[state] = oauth_state
        return oauth_state

    async def _get_oauth_state(self, _session: DBConnection, state: str) -> StubOAuthState | None:
        return self._oauth_states.get(state)

    async def _delete_oauth_state(self, _session: DBConnection, state: str) -> bool:
        return self._oauth_states.pop(state, None) is not None

    async def _delete_individual(self, _session: DBConnection, individual_id: UUID) -> bool:
        if (individual := self._individuals_by_id.pop(individual_id, None)) is None:
            return False
        self._individual_ids_by_email.pop(individual.email.casefold(), None)
        return True

    def _store_oauth_account(self, account: StubOAuthAccount) -> None:
        self._oauth_accounts_by_id[account.id] = account
        self._oauth_accounts_by_provider[(account.provider, account.provider_account_id)] = account.id
        account_key = (account.individual_id, account.provider, account.provider_account_id)
        self._oauth_accounts_by_individual[account_key] = account.id

    async def get_account_by_id(self, session: DBConnection, account_id: UUID) -> StubIndividual | None:
        return await self.get_account_by_id_mock(session, account_id)

    async def update_account(
        self,
        session: DBConnection,
        account_id: UUID,
        **updates: IndividualUpdateValue,
    ) -> StubIndividual | None:
        return await self.update_account_mock(session, account_id, **updates)

    async def create_individual(
        self,
        session: DBConnection,
        email: str,
        name: str | None = None,
        image: str | None = None,
        *,
        email_verified_at: datetime | None = None,
    ) -> StubIndividual:
        return await self.create_individual_mock(
            session,
            email,
            name,
            image,
            email_verified_at=email_verified_at,
        )

    async def get_individual_by_id(self, session: DBConnection, individual_id: UUID) -> StubIndividual | None:
        return await self.get_individual_by_id_mock(session, individual_id)

    async def get_individual_by_email(self, session: DBConnection, email: str) -> StubIndividual | None:
        return await self.get_individual_by_email_mock(session, email)

    async def update_individual(
        self,
        session: DBConnection,
        individual_id: UUID,
        **updates: IndividualUpdateValue,
    ) -> StubIndividual | None:
        return await self.update_individual_mock(session, individual_id, **updates)

    async def create_oauth_account(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount:
        return await self.create_oauth_account_mock(
            session,
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
            **tokens,
        )

    async def get_oauth_account(
        self,
        session: DBConnection,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        return await self.get_oauth_account_mock(session, provider, provider_account_id)

    async def get_oauth_account_by_id(
        self,
        session: DBConnection,
        oauth_account_id: UUID,
    ) -> StubOAuthAccount | None:
        return await self.get_oauth_account_by_id_mock(session, oauth_account_id)

    async def get_oauth_account_by_individual_and_provider(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
    ) -> StubOAuthAccount | None:
        return await self.get_oauth_account_by_individual_and_provider_mock(session, individual_id, provider)

    async def get_oauth_account_by_individual_provider_account_id(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        return await self.get_oauth_account_by_individual_provider_account_id_mock(
            session,
            individual_id,
            provider,
            provider_account_id,
        )

    async def list_oauth_accounts(
        self,
        session: DBConnection,
        individual_id: UUID,
        *,
        provider: str | None = None,
    ) -> list[StubOAuthAccount]:
        return await self.list_oauth_accounts_mock(session, individual_id, provider=provider)

    async def update_oauth_account(
        self,
        session: DBConnection,
        individual_id: UUID,
        provider: str,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount | None:
        return await self.update_oauth_account_mock(session, individual_id, provider, **tokens)

    async def update_oauth_account_by_id(
        self,
        session: DBConnection,
        oauth_account_id: UUID,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount | None:
        return await self.update_oauth_account_by_id_mock(session, oauth_account_id, **tokens)

    async def delete_oauth_account(self, session: DBConnection, oauth_account_id: UUID) -> bool:
        return await self.delete_oauth_account_mock(session, oauth_account_id)

    async def create_session(
        self,
        session: DBConnection,
        individual_id: UUID,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StubSession:
        return await self.create_session_mock(
            session,
            individual_id,
            expires_at,
            ip_address,
            user_agent,
        )

    async def get_session(self, session: DBConnection, session_id: UUID) -> StubSession | None:
        return await self.get_session_mock(session, session_id)

    async def update_session(
        self,
        session: DBConnection,
        session_id: UUID,
        **updates: SessionUpdateValue,
    ) -> StubSession | None:
        return await self.update_session_mock(session, session_id, **updates)

    async def delete_session(self, session: DBConnection, session_id: UUID) -> bool:
        return await self.delete_session_mock(session, session_id)

    async def delete_expired_sessions(self, session: DBConnection) -> int:
        return await self.delete_expired_sessions_mock(session)

    async def create_oauth_state(
        self,
        session: DBConnection,
        state: str,
        expires_at: datetime,
        provider: str | None = None,
        code_verifier: str | None = None,
        nonce: str | None = None,
        intent: OAuthFlowIntent = "signin",
        redirect_url: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: JSONValue = None,
        request_sign_up: bool = False,
        individual_id: UUID | None = None,
    ) -> StubOAuthState:
        return await self.create_oauth_state_mock(
            session,
            state=state,
            expires_at=expires_at,
            provider=provider,
            code_verifier=code_verifier,
            nonce=nonce,
            intent=intent,
            redirect_url=redirect_url,
            error_redirect_url=error_redirect_url,
            new_user_redirect_url=new_user_redirect_url,
            payload=payload,
            request_sign_up=request_sign_up,
            individual_id=individual_id,
        )

    async def get_oauth_state(self, session: DBConnection, state: str) -> StubOAuthState | None:
        return await self.get_oauth_state_mock(session, state)

    async def delete_oauth_state(self, session: DBConnection, state: str) -> bool:
        return await self.delete_oauth_state_mock(session, state)

    async def delete_individual(self, session: DBConnection, individual_id: UUID) -> bool:
        return await self.delete_individual_mock(session, individual_id)


class StubBelgieClient(BelgieClient[StubIndividual, StubOAuthAccount, StubSession, StubOAuthState]):
    after_sign_up_mock: AsyncMock
    get_oauth_account_mock: AsyncMock
    get_oauth_account_for_individual_mock: AsyncMock
    list_oauth_accounts_mock: AsyncMock
    update_individual_mock: AsyncMock
    update_oauth_account_by_id_mock: AsyncMock
    unlink_oauth_account_mock: AsyncMock
    sign_in_individual_mock: AsyncMock
    get_or_create_individual_mock: AsyncMock
    upsert_oauth_account_mock: AsyncMock
    create_session_cookie_mock: MagicMock

    def __init__(
        self,
        *,
        adapter: StubAdapter,
        db: DBConnection | None = None,
        cookie_settings: CookieSettings | None = None,
    ) -> None:
        after_sign_up_mock = AsyncMock()

        async def after_sign_up_callback(
            *,
            client: BelgieClient,
            request: Request | None,
            individual: StubIndividual,
        ) -> None:
            await after_sign_up_mock(client=client, request=request, individual=individual)

        session_manager: SessionManager[StubIndividual, StubOAuthAccount, StubSession, StubOAuthState] = SessionManager(
            adapter,
            max_age=604800,
            update_age=86400,
        )
        super().__init__(
            db=db or StubDBConnection(),
            adapter=adapter,
            session_manager=session_manager,
            cookie_settings=cookie_settings or CookieSettings(secure=False, http_only=True, same_site="lax"),
            after_sign_up=after_sign_up_callback,
        )
        object.__setattr__(self, "after_sign_up_mock", after_sign_up_mock)
        object.__setattr__(self, "get_oauth_account_mock", AsyncMock(side_effect=self._get_oauth_account_default))
        object.__setattr__(
            self,
            "get_oauth_account_for_individual_mock",
            AsyncMock(side_effect=self._get_oauth_account_for_individual_default),
        )
        object.__setattr__(self, "list_oauth_accounts_mock", AsyncMock(side_effect=self._list_oauth_accounts_default))
        object.__setattr__(self, "update_individual_mock", AsyncMock(side_effect=self._update_individual_default))
        object.__setattr__(
            self,
            "update_oauth_account_by_id_mock",
            AsyncMock(side_effect=self._update_oauth_account_by_id_default),
        )
        object.__setattr__(self, "unlink_oauth_account_mock", AsyncMock(side_effect=self._unlink_oauth_account_default))
        object.__setattr__(self, "sign_in_individual_mock", AsyncMock(side_effect=self._sign_in_individual_default))
        object.__setattr__(
            self,
            "get_or_create_individual_mock",
            AsyncMock(side_effect=self._get_or_create_individual_default),
        )
        object.__setattr__(self, "upsert_oauth_account_mock", AsyncMock(side_effect=self._upsert_oauth_account_default))
        object.__setattr__(
            self,
            "create_session_cookie_mock",
            MagicMock(side_effect=self._create_session_cookie_default),
        )

    async def _get_oauth_account_default(
        self,
        *,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        return await BelgieClient.get_oauth_account(
            self,
            provider=provider,
            provider_account_id=provider_account_id,
        )

    async def _get_oauth_account_for_individual_default(
        self,
        *,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        return await BelgieClient.get_oauth_account_for_individual(
            self,
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
        )

    async def _list_oauth_accounts_default(
        self,
        *,
        individual_id: UUID,
        provider: str | None = None,
    ) -> list[StubOAuthAccount]:
        return await BelgieClient.list_oauth_accounts(self, individual_id=individual_id, provider=provider)

    async def _update_individual_default(
        self,
        individual: StubIndividual,
        *,
        request: Request | None = None,
        **updates: IndividualUpdateValue,
    ) -> StubIndividual | None:
        return await BelgieClient.update_individual(
            self,
            individual,
            request=request,
            **updates,
        )

    async def _update_oauth_account_by_id_default(
        self,
        oauth_account_id: UUID,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount | None:
        return await BelgieClient.update_oauth_account_by_id(self, oauth_account_id, **tokens)

    async def _unlink_oauth_account_default(
        self,
        *,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> bool:
        return await BelgieClient.unlink_oauth_account(
            self,
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
        )

    async def _sign_in_individual_default(
        self,
        individual: StubIndividual,
        *,
        request=None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StubSession:
        return await BelgieClient.sign_in_individual(
            self,
            individual,
            request=request,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _get_or_create_individual_default(
        self,
        email: str,
        *,
        name: str | None = None,
        image: str | None = None,
        email_verified_at: datetime | None = None,
    ) -> tuple[StubIndividual, bool]:
        return await BelgieClient.get_or_create_individual(
            self,
            email,
            name=name,
            image=image,
            email_verified_at=email_verified_at,
        )

    async def _upsert_oauth_account_default(
        self,
        *,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount:
        return await BelgieClient.upsert_oauth_account(
            self,
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
            **tokens,
        )

    def _create_session_cookie_default(self, session: StubSession, response):
        return BelgieClient.create_session_cookie(self, session, response)

    async def get_oauth_account(
        self,
        *,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        return await self.get_oauth_account_mock(provider=provider, provider_account_id=provider_account_id)

    async def get_oauth_account_for_individual(
        self,
        *,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> StubOAuthAccount | None:
        return await self.get_oauth_account_for_individual_mock(
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
        )

    async def list_oauth_accounts(
        self,
        *,
        individual_id: UUID,
        provider: str | None = None,
    ) -> list[StubOAuthAccount]:
        return await self.list_oauth_accounts_mock(individual_id=individual_id, provider=provider)

    async def update_individual(
        self,
        individual: StubIndividual,
        *,
        request: Request | None = None,
        **updates: IndividualUpdateValue,
    ) -> StubIndividual | None:
        return await self.update_individual_mock(
            individual,
            request=request,
            **updates,
        )

    async def update_oauth_account_by_id(
        self,
        oauth_account_id: UUID,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount | None:
        return await self.update_oauth_account_by_id_mock(oauth_account_id, **tokens)

    async def unlink_oauth_account(
        self,
        *,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
    ) -> bool:
        return await self.unlink_oauth_account_mock(
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
        )

    async def sign_in_individual(
        self,
        individual: StubIndividual,
        *,
        request=None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StubSession:
        return await self.sign_in_individual_mock(
            individual,
            request=request,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def get_or_create_individual(
        self,
        email: str,
        *,
        name: str | None = None,
        image: str | None = None,
        email_verified_at: datetime | None = None,
    ) -> tuple[StubIndividual, bool]:
        return await self.get_or_create_individual_mock(
            email,
            name=name,
            image=image,
            email_verified_at=email_verified_at,
        )

    async def upsert_oauth_account(
        self,
        *,
        individual_id: UUID,
        provider: str,
        provider_account_id: str,
        **tokens: AccountTokenValue,
    ) -> StubOAuthAccount:
        return await self.upsert_oauth_account_mock(
            individual_id=individual_id,
            provider=provider,
            provider_account_id=provider_account_id,
            **tokens,
        )

    def create_session_cookie(self, session: StubSession, response):
        return self.create_session_cookie_mock(session, response)


class BelgieRuntimeStub:
    def __init__(self, client: StubBelgieClient) -> None:
        self._client = client
        self.settings = BelgieSettings(
            secret="test-secret",
            base_url="http://localhost:8000",
            cookie=CookieSettings(secure=False, http_only=True, same_site="lax"),
        )
        self.after_authenticate_mock = AsyncMock()
        self.__signature__ = Signature()

    async def __call__(self, *args: object, **kwargs: object) -> StubBelgieClient:
        return self._client

    async def after_authenticate(
        self,
        *,
        client: BelgieClient,
        request: Request,
        individual: IndividualProtocol[str],
        profile: AuthenticatedProfile,
    ) -> None:
        await self.after_authenticate_mock(
            client=client,
            request=request,
            individual=individual,
            profile=profile,
        )


def _string_or_none(value: AccountTokenValue | IndividualUpdateValue | SessionUpdateValue) -> str | None:
    if value is None or isinstance(value, str):
        return value
    msg = "expected string value"
    raise TypeError(msg)


def _datetime_or_none(value: AccountTokenValue | IndividualUpdateValue | SessionUpdateValue) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    msg = "expected datetime value"
    raise TypeError(msg)


def _build_plugin(
    *,
    client_id: str | list[str] = "test-client-id",
    discovery_url: str | None = None,
    authorization_endpoint: str | None = "https://idp.example.com/oauth2/authorize",
    token_endpoint: str | None = "https://idp.example.com/oauth2/token",
    userinfo_endpoint: str | None = "https://idp.example.com/userinfo",
    issuer: str | None = None,
    jwks_uri: str | None = None,
    state_strategy: OAuthStateStrategy = "adapter",
    response_mode: OAuthResponseMode | None = None,
    disable_sign_up: bool = False,
    disable_implicit_sign_up: bool = False,
    disable_id_token_sign_in: bool = False,
    update_account_on_sign_in: bool = True,
    trusted_for_account_linking: bool = False,
    override_user_info_on_sign_in: bool = False,
    store_account_cookie: bool = False,
    default_error_redirect_url: str | None = None,
    encrypt_tokens: bool = False,
    get_token: TokenExchangeOverride | None = None,
    refresh_tokens: TokenRefreshOverride | None = None,
    get_userinfo: UserInfoFetcher | None = None,
    map_profile: ProfileMapper | None = None,
) -> OAuthPlugin:
    belgie_settings = BelgieSettings(
        secret="test-secret",
        base_url="http://localhost:8000",
        cookie=CookieSettings(secure=False, http_only=True, same_site="lax"),
    )
    provider = OAuthProvider(
        provider_id="acme",
        client_id=client_id,
        client_secret=SecretStr("test-client-secret"),
        discovery_url=discovery_url,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        userinfo_endpoint=userinfo_endpoint,
        issuer=issuer,
        jwks_uri=jwks_uri,
        scopes=["openid", "email", "profile"],
        access_type="offline",
        prompt="consent",
        state_strategy=state_strategy,
        response_mode=response_mode,
        disable_sign_up=disable_sign_up,
        disable_implicit_sign_up=disable_implicit_sign_up,
        disable_id_token_sign_in=disable_id_token_sign_in,
        update_account_on_sign_in=update_account_on_sign_in,
        trusted_for_account_linking=trusted_for_account_linking,
        override_user_info_on_sign_in=override_user_info_on_sign_in,
        store_account_cookie=store_account_cookie,
        default_error_redirect_url=default_error_redirect_url,
        encrypt_tokens=encrypt_tokens,
        get_token=get_token,
        refresh_tokens=refresh_tokens,
        get_userinfo=get_userinfo,
        map_profile=map_profile,
    )
    return OAuthPlugin(belgie_settings, provider)


def _build_state(
    *,
    state: str = "test-state",
    provider: str | None = "acme",
    individual_id: UUID | None = None,
    code_verifier: str | None = "test-verifier",
    nonce: str | None = "test-nonce",
    intent: OAuthFlowIntent = "signin",
    redirect_url: str | None = "/after",
    error_redirect_url: str | None = None,
    new_user_redirect_url: str | None = None,
    payload: JSONValue = None,
    request_sign_up: bool = False,
    expires_at: datetime | None = None,
) -> StubOAuthState:
    return StubOAuthState(
        state=state,
        provider=provider,
        individual_id=individual_id,
        code_verifier=code_verifier,
        nonce=nonce,
        intent=intent,
        redirect_url=redirect_url,
        error_redirect_url=error_redirect_url,
        new_user_redirect_url=new_user_redirect_url,
        payload=payload,
        request_sign_up=request_sign_up,
        expires_at=expires_at or (_naive_now() + timedelta(minutes=5)),
    )


def _build_individual(
    *,
    id: UUID | None = None,
    email: str = "person@example.com",
    email_verified_at: datetime | None = None,
    name: str | None = None,
    image: str | None = None,
) -> StubIndividual:
    return StubIndividual(
        id=id or uuid4(),
        email=email,
        email_verified_at=email_verified_at,
        name=name,
        image=image,
    )


def _build_account(
    *,
    id: UUID | None = None,
    individual_id: UUID | None = None,
    provider_account_id: str = "provider-account-1",
    access_token: str | None = "access-token",
    refresh_token: str | None = "refresh-token",
    access_token_expires_at: datetime | None = None,
    refresh_token_expires_at: datetime | None = None,
    token_type: str | None = "Bearer",
    scope: str | None = "openid email profile",
    id_token: str | None = None,
) -> StubOAuthAccount:
    return StubOAuthAccount(
        id=id or uuid4(),
        individual_id=individual_id or uuid4(),
        provider_account_id=provider_account_id,
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_at=access_token_expires_at or (_naive_now() + timedelta(hours=1)),
        refresh_token_expires_at=refresh_token_expires_at or (_naive_now() + timedelta(days=30)),
        token_type=token_type,
        scope=scope,
        id_token=id_token,
    )


def _build_session(
    *,
    id: UUID | None = None,
    individual_id: UUID | None = None,
) -> StubSession:
    return StubSession(
        id=id or uuid4(),
        individual_id=individual_id or uuid4(),
    )


def _build_client(*, adapter: StubAdapter | None = None) -> StubBelgieClient:
    return StubBelgieClient(adapter=adapter or StubAdapter())


def _build_app(plugin: OAuthPlugin, client_dependency: StubBelgieClient) -> FastAPI:
    belgie = BelgieRuntimeStub(client_dependency)
    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    app.state.belgie = belgie
    return app


def _build_state_adapter() -> StubAdapter:
    return StubAdapter()


def _token_set() -> OAuthTokenSet:
    return OAuthTokenSet(
        access_token="access-token",
        token_type="Bearer",
        refresh_token="refresh-token",
        scope="openid email profile",
        id_token="id-token",
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        refresh_token_expires_at=datetime.now(UTC) + timedelta(days=30),
        raw={
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile",
            "id_token": "id-token",
            "token_type": "Bearer",
        },
    )


def _linked_account(
    *,
    id: UUID | None = None,
    individual_id: UUID | None = None,
    provider_account_id: str = "provider-account-1",
    access_token: str | None = "access-token",
    access_token_expires_at: datetime | None = None,
) -> OAuthLinkedAccount:
    return OAuthLinkedAccount(
        id=id or uuid4(),
        individual_id=individual_id or uuid4(),
        provider="acme",
        provider_account_id=provider_account_id,
        access_token=access_token,
        refresh_token="refresh-token",
        access_token_expires_at=access_token_expires_at or (datetime.now(UTC) + timedelta(hours=1)),
        refresh_token_expires_at=datetime.now(UTC) + timedelta(days=30),
        token_type="Bearer",
        scope="openid email profile",
        id_token=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _path_and_query(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


def _start_provider_flow(test_client: TestClient, start_url: str) -> tuple[str, str]:
    response = test_client.get(_path_and_query(start_url), follow_redirects=False)
    assert response.status_code == 302
    provider_url = response.headers["location"]
    state = parse_qs(urlparse(provider_url).query)["state"][0]
    return provider_url, state


def _issue_acme_id_token(
    *,
    signing_key,
    subject: str = "provider-account-1",
    nonce: str = "direct-nonce",
    email: str | None = "person@example.com",
    email_verified: bool = True,
) -> str:
    claims: dict[str, JSONValue] = {
        "email_verified": email_verified,
        "name": "Test Person",
        "picture": "https://example.com/photo.jpg",
    }
    if email is not None:
        claims["email"] = email
    return issue_id_token(
        signing_key=signing_key,
        issuer="https://idp.example.com",
        audience="test-client-id",
        subject=subject,
        nonce=nonce,
        claims=claims,
    )


def _mock_acme_jwks(signing_key) -> None:
    respx.get("https://idp.example.com/jwks").mock(
        return_value=httpx.Response(200, json=build_jwks_document(signing_key)),
    )


def _cookie_names(test_client: TestClient) -> set[str]:
    return {cookie.name for cookie in test_client.cookies.jar}


def test_provider_requires_discovery_or_manual_endpoints() -> None:
    with pytest.raises(ValidationError):
        OAuthProvider(
            provider_id="acme",
            client_id="client-id",
            client_secret=SecretStr("client-secret"),
        )


def test_provider_rejects_empty_client_id_list() -> None:
    with pytest.raises(ValidationError):
        OAuthProvider(
            provider_id="acme",
            client_id=[],
            client_secret=SecretStr("client-secret"),
            authorization_endpoint="https://idp.example.com/oauth2/authorize",
            token_endpoint="https://idp.example.com/oauth2/token",
        )


def test_dependency_requires_router_initialization() -> None:
    plugin = _build_plugin()

    with pytest.raises(RuntimeError, match=r"router initialization"):
        plugin()


def test_plugin_dependency_injects_client_with_request_and_response() -> None:
    plugin = _build_plugin()
    app = _build_app(plugin, _build_client())

    @app.get("/uses-plugin")
    async def uses_plugin(oauth: OAuthClient = Depends(plugin)) -> dict[str, str]:
        request_path = oauth.request.url.path if oauth.request is not None else ""
        response_attached = "yes" if oauth.response is not None else "no"
        return {
            "provider": oauth.plugin.provider_id,
            "request_path": request_path,
            "response_attached": response_attached,
        }

    response = TestClient(app).get("/uses-plugin")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "acme",
        "request_path": "/uses-plugin",
        "response_attached": "yes",
    }


def test_provider_provider_is_cached_self() -> None:
    provider = OAuthProvider(
        provider_id="acme",
        client_id="client-id",
        client_secret=SecretStr("client-secret"),
        authorization_endpoint="https://idp.example.com/oauth2/authorize",
        token_endpoint="https://idp.example.com/oauth2/token",
    )

    assert provider.provider is provider
    assert provider.provider is provider


@pytest.mark.asyncio
async def test_missing_callback_state_uses_default_error_redirect() -> None:
    plugin = _build_plugin(default_error_redirect_url="/oauth-error")
    app = _build_app(plugin, _build_client())

    with TestClient(app) as test_client:
        response = test_client.get("/auth/provider/acme/callback", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/oauth-error?error=state_mismatch"


@pytest.mark.asyncio
async def test_signin_url_uses_start_route_and_persists_adapter_state() -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url(
        return_to="/after",
        error_redirect_url="/error",
        new_user_redirect_url="/welcome",
        payload={"source": "landing"},
        request_sign_up=True,
    )

    adapter.create_oauth_state_mock.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        provider="acme",
        code_verifier=ANY,
        nonce=ANY,
        intent="signin",
        redirect_url="/after",
        error_redirect_url="/error",
        new_user_redirect_url="/welcome",
        payload={"source": "landing"},
        request_sign_up=True,
        individual_id=None,
    )
    assert urlparse(start_url).netloc == "localhost:8000"

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        query = parse_qs(urlparse(provider_url).query)

    assert urlparse(provider_url).netloc == "idp.example.com"
    assert query["prompt"][0] == "consent"
    assert query["access_type"][0] == "offline"
    assert query["nonce"][0]
    assert query["code_challenge"][0]
    assert query["code_challenge_method"][0] == "S256"


@pytest.mark.asyncio
async def test_signin_url_uses_primary_client_id_from_list() -> None:
    plugin = _build_plugin(client_id=["primary-client-id", "secondary-client-id"])
    client_dependency = _build_client(adapter=_build_state_adapter())
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url()

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        query = parse_qs(urlparse(provider_url).query)

    assert query["client_id"][0] == "primary-client-id"


@pytest.mark.asyncio
async def test_link_url_persists_link_intent_and_individual() -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    individual_id = uuid4()
    start_url = await oauth_client.link_url(
        individual_id=individual_id,
        return_to="/linked",
        payload={"flow": "link"},
    )

    adapter.create_oauth_state_mock.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        provider="acme",
        code_verifier=ANY,
        nonce=ANY,
        intent="link",
        redirect_url="/linked",
        error_redirect_url=None,
        new_user_redirect_url=None,
        payload={"flow": "link"},
        request_sign_up=False,
        individual_id=individual_id,
    )

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)

    assert provider_url.startswith("https://idp.example.com/oauth2/authorize")


@pytest.mark.asyncio
async def test_cookie_state_strategy_uses_cookie_store_and_trampoline() -> None:
    plugin = _build_plugin(state_strategy="cookie")
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url(payload={"flow": "cookie"})

    adapter.create_oauth_state_mock.assert_not_awaited()
    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        assert "belgie_oauth_acme_state" in _cookie_names(test_client)

    assert provider_url.startswith("https://idp.example.com/oauth2/authorize")


@pytest.mark.asyncio
async def test_signin_url_supports_additional_scope_reconsent() -> None:
    plugin = _build_plugin()
    client_dependency = _build_client(adapter=_build_state_adapter())
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url(
        scopes=["openid", "email", "calendar.read"],
        prompt="select_account",
        payload={"scope": "expanded"},
    )

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        query = parse_qs(urlparse(provider_url).query)

    assert query["scope"][0] == "openid email calendar.read"
    assert query["prompt"][0] == "select_account"


@pytest.mark.asyncio
@respx.mock
async def test_resolve_server_metadata_uses_discovery_and_caches() -> None:
    discovery_url = "https://accounts.example.com/.well-known/openid-configuration"
    plugin = _build_plugin(
        discovery_url=discovery_url,
        authorization_endpoint=None,
        token_endpoint=None,
        userinfo_endpoint=None,
    )
    respx.get(discovery_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_endpoint": "https://accounts.example.com/authorize",
                "token_endpoint": "https://accounts.example.com/token",
                "userinfo_endpoint": "https://accounts.example.com/userinfo",
                "issuer": "https://accounts.example.com",
                "jwks_uri": "https://accounts.example.com/jwks",
            },
        ),
    )

    metadata_first = await plugin.resolve_server_metadata()
    metadata_second = await plugin.resolve_server_metadata()

    assert metadata_first["authorization_endpoint"] == "https://accounts.example.com/authorize"
    assert metadata_second["issuer"] == "https://accounts.example.com"
    assert len(respx.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_uses_manual_token_endpoint() -> None:
    plugin = _build_plugin()
    respx.post("https://idp.example.com/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "scope": "openid email profile",
                "expires_in": 3600,
                "refresh_token_expires_in": 7200,
                "id_token": "test-id-token",
            },
        ),
    )

    token_set = await plugin.exchange_code_for_tokens("test-code", code_verifier="verifier")

    assert token_set.access_token == "new-access-token"
    assert token_set.refresh_token == "new-refresh-token"
    assert token_set.id_token == "test-id-token"
    assert token_set.access_token_expires_at is not None
    assert token_set.refresh_token_expires_at is not None


@pytest.mark.asyncio
async def test_custom_get_token_success_and_failure_paths() -> None:
    async def get_token_success(
        _oauth_client,
        code: str,
        token_params: dict[str, str],
        code_verifier: str | None,
    ) -> dict[str, JSONValue]:
        assert code == "custom-code"
        assert token_params == {}
        assert code_verifier == "custom-verifier"
        return {
            "access_token": "custom-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

    success_plugin = _build_plugin(get_token=get_token_success)

    token_set = await success_plugin.exchange_code_for_tokens("custom-code", code_verifier="custom-verifier")

    assert token_set.access_token == "custom-access-token"

    async def get_token_failure(
        _oauth_client,
        _code: str,
        _token_params: dict[str, str],
        _code_verifier: str | None,
    ) -> dict[str, JSONValue]:
        msg = "custom token exchange failed"
        raise OAuthError(msg)

    failure_plugin = _build_plugin(get_token=get_token_failure)

    with pytest.raises(OAuthError, match="custom token exchange failed"):
        await failure_plugin.exchange_code_for_tokens("custom-code", code_verifier="custom-verifier")


@pytest.mark.asyncio
@respx.mock
async def test_async_map_profile_is_awaited_for_id_token_profile() -> None:
    async def map_profile(raw_profile: dict[str, JSONValue], token_set: OAuthTokenSet) -> OAuthUserInfo:
        assert token_set.id_token is not None
        return OAuthUserInfo(
            provider_account_id=str(raw_profile["sub"]),
            email="mapped@example.com",
            email_verified=True,
            name="Mapped Person",
            raw=dict(raw_profile),
        )

    plugin = _build_plugin(
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
        map_profile=map_profile,
    )
    signing_key = build_rsa_signing_key(kid="async-map-profile")
    _mock_acme_jwks(signing_key)
    token_set = OAuthTokenSet.from_id_token(
        id_token=_issue_acme_id_token(signing_key=signing_key, subject="async-profile"),
    )

    profile = await plugin._transport.fetch_id_token_profile(token_set, nonce="direct-nonce")

    assert profile.provider_account_id == "async-profile"
    assert profile.email == "mapped@example.com"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_provider_profile_accepts_secondary_client_id_audience() -> None:
    plugin = _build_plugin(
        client_id=["primary-client-id", "secondary-client-id"],
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    signing_key = build_rsa_signing_key(kid="multi-client-key")
    nonce = "multi-client-nonce"
    id_token = issue_id_token(
        signing_key=signing_key,
        issuer="https://idp.example.com",
        audience="secondary-client-id",
        subject="provider-account-1",
        nonce=nonce,
        claims={
            "email": "person@example.com",
            "email_verified": True,
            "name": "Test Person",
        },
    )

    respx.get("https://idp.example.com/jwks").mock(
        return_value=httpx.Response(200, json=build_jwks_document(signing_key)),
    )

    profile = await plugin._transport.fetch_provider_profile(
        OAuthTokenSet.from_response(
            {
                "access_token": "access-token",
                "token_type": "Bearer",
                "id_token": id_token,
                "expires_in": 3600,
            },
        ),
        nonce=nonce,
    )

    assert profile.provider_account_id == "provider-account-1"
    assert profile.email == "person@example.com"
    assert profile.email_verified is True


@pytest.mark.asyncio
@respx.mock
async def test_id_token_signin_creates_session_account_and_json_response() -> None:
    plugin = _build_plugin(
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    app = _build_app(plugin, client_dependency)
    signing_key = build_rsa_signing_key(kid="direct-signin")
    _mock_acme_jwks(signing_key)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key),
                "nonce": "direct-nonce",
                "access_token": "direct-access-token",
                "refresh_token": "direct-refresh-token",
                "token_type": "Bearer",
                "scope": "openid email profile",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["redirect"] is False
    assert payload["token"]
    assert payload["individual"]["email"] == "person@example.com"
    assert "belgie_session" in response.cookies
    client_dependency.after_sign_up_mock.assert_awaited_once()
    app.state.belgie.after_authenticate_mock.assert_awaited_once()
    account = next(iter(adapter._oauth_accounts_by_id.values()))
    assert account.provider_account_id == "provider-account-1"
    assert account.access_token == "direct-access-token"
    assert account.refresh_token == "direct-refresh-token"


@pytest.mark.asyncio
@respx.mock
async def test_id_token_signin_existing_account_updates_tokens() -> None:
    plugin = _build_plugin(
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    adapter = _build_state_adapter()
    individual = _build_individual(email="person@example.com")
    adapter._individuals_by_id[individual.id] = individual
    adapter._individual_ids_by_email[individual.email.casefold()] = individual.id
    adapter._store_oauth_account(
        _build_account(
            individual_id=individual.id,
            provider_account_id="provider-account-1",
            access_token="old-access-token",
            id_token="old-id-token",
        ),
    )
    app = _build_app(plugin, _build_client(adapter=adapter))
    signing_key = build_rsa_signing_key(kid="direct-update")
    _mock_acme_jwks(signing_key)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key),
                "nonce": "direct-nonce",
                "access_token": "new-access-token",
            },
        )

    assert response.status_code == 200
    account = next(iter(adapter._oauth_accounts_by_id.values()))
    assert account.access_token == "new-access-token"
    assert account.id_token != "old-id-token"


@pytest.mark.asyncio
@respx.mock
async def test_id_token_signin_rejects_disabled_missing_email_and_untrusted_linking() -> None:
    signing_key = build_rsa_signing_key(kid="direct-reject")
    _mock_acme_jwks(signing_key)

    disabled_plugin = _build_plugin(
        disable_id_token_sign_in=True,
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    with TestClient(_build_app(disabled_plugin, _build_client())) as test_client:
        disabled_response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key),
                "nonce": "direct-nonce",
            },
        )
    assert disabled_response.status_code == 400
    assert disabled_response.json()["detail"] == "id_token_sign_in_disabled"

    missing_email_plugin = _build_plugin(
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    with TestClient(_build_app(missing_email_plugin, _build_client())) as test_client:
        missing_email_response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key, subject="missing-email", email=None),
                "nonce": "direct-nonce",
            },
        )
    assert missing_email_response.status_code == 400
    assert missing_email_response.json()["detail"] == "email_missing"

    adapter = _build_state_adapter()
    individual = _build_individual(email="person@example.com")
    adapter._individuals_by_id[individual.id] = individual
    adapter._individual_ids_by_email[individual.email.casefold()] = individual.id
    untrusted_plugin = _build_plugin(
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    with TestClient(_build_app(untrusted_plugin, _build_client(adapter=adapter))) as test_client:
        untrusted_response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key, email_verified=False),
                "nonce": "direct-nonce",
            },
        )
    assert untrusted_response.status_code == 400
    assert untrusted_response.json()["detail"] == "account_not_linked"


@pytest.mark.asyncio
@respx.mock
async def test_id_token_link_succeeds_idempotently_and_rejects_mismatch() -> None:
    plugin = _build_plugin(
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    adapter = _build_state_adapter()
    individual = _build_individual(email="person@example.com", email_verified_at=_naive_now())
    session = _build_session(individual_id=individual.id)
    adapter._individuals_by_id[individual.id] = individual
    adapter._individual_ids_by_email[individual.email.casefold()] = individual.id
    adapter._sessions[session.id] = session
    app = _build_app(plugin, _build_client(adapter=adapter))
    signing_key = build_rsa_signing_key(kid="direct-link")
    _mock_acme_jwks(signing_key)

    with TestClient(app) as test_client:
        test_client.cookies.set("belgie_session", str(session.id))
        first = test_client.post(
            "/auth/provider/acme/link/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key, subject="linked-account"),
                "nonce": "direct-nonce",
                "access_token": "link-access-token",
            },
        )
        second = test_client.post(
            "/auth/provider/acme/link/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key, subject="linked-account"),
                "nonce": "direct-nonce",
                "access_token": "link-access-token-2",
            },
        )
        mismatch = test_client.post(
            "/auth/provider/acme/link/id-token",
            json={
                "id_token": _issue_acme_id_token(
                    signing_key=signing_key,
                    subject="mismatch-account",
                    email="other@example.com",
                ),
                "nonce": "direct-nonce",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert mismatch.status_code == 400
    assert mismatch.json()["detail"] == "email_does_not_match"
    account = next(iter(adapter._oauth_accounts_by_id.values()))
    assert account.provider_account_id == "linked-account"
    assert account.access_token == "link-access-token-2"


@pytest.mark.asyncio
@respx.mock
async def test_account_cookie_signin_allows_access_token_without_provider_account_id() -> None:
    plugin = _build_plugin(
        store_account_cookie=True,
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    adapter = _build_state_adapter()
    app = _build_app(plugin, _build_client(adapter=adapter))
    signing_key = build_rsa_signing_key(kid="account-cookie")
    _mock_acme_jwks(signing_key)

    with TestClient(app) as test_client:
        signin_response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key),
                "nonce": "direct-nonce",
                "access_token": "cookie-access-token",
                "refresh_token": "cookie-refresh-token",
                "token_type": "Bearer",
                "scope": "openid email profile",
            },
        )
        token_response = test_client.post("/auth/provider/acme/access-token", json={})

    assert signin_response.status_code == 200
    assert "belgie_oauth_acme_account" in signin_response.cookies
    assert token_response.status_code == 200
    assert token_response.json()["access_token"] == "cookie-access-token"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_persists_tokens_and_updates_account_cookie() -> None:
    plugin = _build_plugin(
        store_account_cookie=True,
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    adapter = _build_state_adapter()
    app = _build_app(plugin, _build_client(adapter=adapter))
    signing_key = build_rsa_signing_key(kid="refresh-cookie")
    _mock_acme_jwks(signing_key)
    respx.post("https://idp.example.com/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh-access-token",
                "refresh_token": "fresh-refresh-token",
                "token_type": "Bearer",
                "scope": "openid email profile",
                "expires_in": 3600,
                "id_token": "fresh-id-token",
            },
        ),
    )

    with TestClient(app) as test_client:
        signin_response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key),
                "nonce": "direct-nonce",
                "access_token": "stale-access-token",
                "refresh_token": "stale-refresh-token",
            },
        )
        refresh_response = test_client.post("/auth/provider/acme/refresh-token", json={})

    assert signin_response.status_code == 200
    assert refresh_response.status_code == 200
    assert "belgie_oauth_acme_account" in refresh_response.cookies
    payload = refresh_response.json()
    assert payload["access_token"] == "fresh-access-token"
    assert payload["refresh_token"] == "fresh-refresh-token"
    account = next(iter(adapter._oauth_accounts_by_id.values()))
    assert account.access_token == "fresh-access-token"
    assert account.refresh_token == "fresh-refresh-token"
    assert account.id_token == "fresh-id-token"


@pytest.mark.asyncio
@respx.mock
async def test_account_cookie_stale_cookie_requires_db_account_or_explicit_id() -> None:
    plugin = _build_plugin(
        store_account_cookie=True,
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    adapter = _build_state_adapter()
    app = _build_app(plugin, _build_client(adapter=adapter))
    signing_key = build_rsa_signing_key(kid="stale-cookie")
    _mock_acme_jwks(signing_key)

    with TestClient(app) as test_client:
        signin_response = test_client.post(
            "/auth/provider/acme/signin/id-token",
            json={
                "id_token": _issue_acme_id_token(signing_key=signing_key),
                "nonce": "direct-nonce",
                "access_token": "first-access-token",
            },
        )
        account = next(iter(adapter._oauth_accounts_by_id.values()))
        adapter._oauth_accounts_by_id.clear()
        adapter._oauth_accounts_by_provider.clear()
        adapter._oauth_accounts_by_individual.clear()
        missing_response = test_client.post("/auth/provider/acme/access-token", json={})
        adapter._store_oauth_account(replace(account, access_token="explicit-access-token"))
        explicit_response = test_client.post(
            "/auth/provider/acme/access-token",
            json={"provider_account_id": account.provider_account_id},
        )

    assert signin_response.status_code == 200
    assert missing_response.status_code == 400
    assert missing_response.json()["detail"] == "oauth account not found"
    assert explicit_response.status_code == 200
    assert explicit_response.json()["access_token"] == "explicit-access-token"


@pytest.mark.asyncio
async def test_callback_signin_new_user_exposes_payload_on_request_state(monkeypatch) -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    user = _build_individual(email="person@example.com")
    session = _build_session(individual_id=user.id)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    _set_async_return(client_dependency.get_or_create_individual_mock, (user, True))
    _set_async_return(client_dependency.sign_in_individual_mock, session)
    app = _build_app(plugin, client_dependency)

    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)
    with TestClient(app) as test_client:
        # The trampoline sets the browser-bound state marker before the provider redirect.
        start_url = await oauth_client.signin_url(
            return_to="/after",
            error_redirect_url="/error",
            new_user_redirect_url="/welcome",
            payload={"flow": "signin"},
            request_sign_up=True,
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(
            plugin._transport,
            "resolve_server_metadata",
            AsyncMock(return_value={"issuer": "https://idp.example.com"}),
        )
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=True,
                    name="Test Person",
                    image="https://example.com/photo.jpg",
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}&iss=https%3A%2F%2Fidp.example.com",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/welcome"
    client_dependency.after_sign_up_mock.assert_awaited_once()
    client_dependency.upsert_oauth_account_mock.assert_awaited_once_with(
        individual_id=user.id,
        provider="acme",
        provider_account_id="provider-account-1",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=ANY,
        refresh_token_expires_at=ANY,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )

    request = app.state.belgie.after_authenticate_mock.await_args.kwargs["request"]
    assert request.state.oauth_payload == {"flow": "signin"}
    assert request.state.oauth_state.intent == "signin"
    assert request.state.oauth_state.request_sign_up is True


@pytest.mark.asyncio
async def test_callback_link_flow_does_not_set_session_cookie(monkeypatch) -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    adapter = _build_state_adapter()
    linked_individual = _build_individual(id=individual_id, email="linked@example.com")
    _set_async_return(adapter.get_individual_by_id_mock, linked_individual)
    _set_async_return(adapter.update_individual_mock, linked_individual)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    app = _build_app(plugin, client_dependency)

    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)
    with TestClient(app) as test_client:
        start_url = await oauth_client.link_url(
            individual_id=individual_id,
            return_to="/linked",
            payload={"flow": "link"},
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-2",
                    email="linked@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-2"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/linked"
    client_dependency.upsert_oauth_account_mock.assert_awaited_once_with(
        individual_id=individual_id,
        provider="acme",
        provider_account_id="provider-account-2",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=ANY,
        refresh_token_expires_at=ANY,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )
    client_dependency.create_session_cookie_mock.assert_not_called()
    app.state.belgie.after_authenticate_mock.assert_not_awaited()


def test_callback_rejects_invalid_state() -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    _set_async_return(adapter.get_oauth_state_mock, None)
    client_dependency = _build_client(adapter=adapter)
    app = _build_app(plugin, client_dependency)

    with pytest.raises(InvalidStateError):
        TestClient(app).get("/auth/provider/acme/callback?code=test-code&state=missing")


def test_adapter_state_rejects_missing_marker_cookie() -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    _set_async_return(adapter.get_oauth_state_mock, _build_state())
    client_dependency = _build_client(adapter=adapter)
    app = _build_app(plugin, client_dependency)

    with pytest.raises(InvalidStateError, match="marker"):
        TestClient(app).get("/auth/provider/acme/callback?code=test-code&state=test-state")


def test_cookie_state_rejects_missing_state_cookie() -> None:
    plugin = _build_plugin(state_strategy="cookie")
    client_dependency = _build_client(adapter=_build_state_adapter())
    app = _build_app(plugin, client_dependency)

    with pytest.raises(InvalidStateError, match="state cookie"):
        TestClient(app).get("/auth/provider/acme/callback?code=test-code&state=test-state")


def test_cookie_state_form_post_normalizes_before_validation() -> None:
    plugin = _build_plugin(state_strategy="cookie", response_mode="form_post")
    client_dependency = _build_client(adapter=_build_state_adapter())
    app = _build_app(plugin, client_dependency)

    response = TestClient(app).post(
        "/auth/provider/acme/callback",
        data={"code": "test-code", "state": "test-state", "iss": "https://idp.example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith(
        "/auth/provider/acme/callback?code=test-code&state=test-state&iss=https%3A%2F%2Fidp.example.com",
    )


@pytest.mark.asyncio
async def test_callback_rejects_issuer_mismatch(monkeypatch) -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(
            plugin._transport,
            "resolve_server_metadata",
            AsyncMock(return_value={"issuer": "https://idp.example.com"}),
        )
        with pytest.raises(OAuthError, match="issuer mismatch"):
            test_client.get(
                f"/auth/provider/acme/callback?code=test-code&state={state}&iss=https%3A%2F%2Fevil.example",
            )


@pytest.mark.asyncio
async def test_callback_redirects_to_error_url_on_oauth_failure(monkeypatch) -> None:
    plugin = _build_plugin(default_error_redirect_url="/oauth-error")
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(
            plugin._transport,
            "exchange_code_for_tokens",
            AsyncMock(side_effect=OAuthError("bad token")),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=oauth_code_verification_failed"


@pytest.mark.asyncio
async def test_callback_uses_default_error_redirect_after_state_consumption(monkeypatch) -> None:
    plugin = _build_plugin(default_error_redirect_url="/oauth-error")
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(
            plugin._transport,
            "exchange_code_for_tokens",
            AsyncMock(side_effect=OAuthError("bad token")),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/oauth-error?error=oauth_code_verification_failed"


@pytest.mark.asyncio
async def test_signin_disallows_signup_when_provider_forbids_it(monkeypatch) -> None:
    plugin = _build_plugin(disable_sign_up=True)
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="new@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=signup_disabled"
    client_dependency.get_or_create_individual_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_signin_requires_explicit_signup_flag(monkeypatch) -> None:
    plugin = _build_plugin(disable_implicit_sign_up=True)
    adapter = _build_state_adapter()
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="new@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=signup_disabled"
    client_dependency.get_or_create_individual_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_account_signin_can_skip_account_updates(monkeypatch) -> None:
    plugin = _build_plugin(update_account_on_sign_in=False)
    individual = _build_individual(email="person@example.com")
    existing_account = _build_account(individual_id=individual.id, provider_account_id="provider-account-1")
    session = _build_session(individual_id=individual.id)
    adapter = _build_state_adapter()
    _set_async_return(adapter.get_individual_by_id_mock, individual)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, existing_account)
    _set_async_return(client_dependency.sign_in_individual_mock, session)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(return_to="/after")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=False,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/after"
    client_dependency.update_oauth_account_by_id_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_signin_implicitly_links_existing_verified_user(monkeypatch) -> None:
    plugin = _build_plugin()
    individual = _build_individual(email="person@example.com")
    session = _build_session(individual_id=individual.id)
    adapter = _build_state_adapter()
    _set_async_return(adapter.get_individual_by_email_mock, individual)
    _set_async_return(adapter.update_individual_mock, individual)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    _set_async_return(client_dependency.get_or_create_individual_mock, (individual, False))
    _set_async_return(client_dependency.sign_in_individual_mock, session)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    client_dependency.upsert_oauth_account_mock.assert_awaited_once_with(
        individual_id=individual.id,
        provider="acme",
        provider_account_id="provider-account-1",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=ANY,
        refresh_token_expires_at=ANY,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )


@pytest.mark.asyncio
async def test_signin_rejects_untrusted_implicit_linking(monkeypatch) -> None:
    plugin = _build_plugin()
    individual = _build_individual(email="person@example.com")
    adapter = _build_state_adapter()
    _set_async_return(adapter.get_individual_by_email_mock, individual)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=False,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=account_not_linked"
    client_dependency.get_or_create_individual_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_signin_trusted_provider_can_implicitly_link_unverified_email(monkeypatch) -> None:
    plugin = _build_plugin(trusted_for_account_linking=True)
    individual = _build_individual(email="person@example.com")
    session = _build_session(individual_id=individual.id)
    adapter = _build_state_adapter()
    _set_async_return(adapter.get_individual_by_email_mock, individual)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    _set_async_return(client_dependency.get_or_create_individual_mock, (individual, False))
    _set_async_return(client_dependency.sign_in_individual_mock, session)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=False,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    client_dependency.upsert_oauth_account_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_flow_rejects_mismatched_email(monkeypatch) -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    adapter = _build_state_adapter()
    owner = _build_individual(id=individual_id, email="owner@example.com")
    _set_async_return(adapter.get_individual_by_id_mock, owner)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.link_url(
            individual_id=individual_id,
            return_to="/linked",
            error_redirect_url="/error",
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-2",
                    email="other@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-2"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=email_does_not_match"
    client_dependency.upsert_oauth_account_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_flow_rejects_missing_email(monkeypatch) -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    adapter = _build_state_adapter()
    owner = _build_individual(id=individual_id, email="owner@example.com")
    _set_async_return(adapter.get_individual_by_id_mock, owner)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, None)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.link_url(
            individual_id=individual_id,
            return_to="/linked",
            error_redirect_url="/error",
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-2",
                    email=None,
                    email_verified=False,
                    raw={"sub": "provider-account-2"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=email_missing"
    client_dependency.upsert_oauth_account_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_verification_only_updates_when_provider_email_matches(monkeypatch) -> None:
    plugin = _build_plugin(override_user_info_on_sign_in=True)
    individual = _build_individual(email="person@example.com")
    updated_individual = _build_individual(id=individual.id, email=individual.email)
    existing_account = _build_account(individual_id=individual.id, provider_account_id="provider-account-1")
    session = _build_session(individual_id=individual.id)
    adapter = _build_state_adapter()
    _set_async_return(adapter.get_individual_by_id_mock, individual)
    _set_async_return(adapter.update_individual_mock, updated_individual)
    client_dependency = _build_client(adapter=adapter)
    _set_async_return(client_dependency.get_oauth_account_mock, existing_account)
    _set_async_return(client_dependency.sign_in_individual_mock, session)
    _set_async_return(client_dependency.update_oauth_account_by_id_mock, existing_account)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin.client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="other@example.com",
                    email_verified=True,
                    name="Updated Name",
                    image="https://example.com/photo.jpg",
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    client_update_call = client_dependency.update_individual_mock.await_args
    assert client_update_call is not None
    assert client_update_call.args == (individual,)
    assert client_update_call.kwargs["request"].url.path == "/auth/provider/acme/callback"
    update_call = adapter.update_individual_mock.await_args
    assert update_call is not None
    update_kwargs = update_call.kwargs
    assert update_kwargs["name"] == "Updated Name"
    assert update_kwargs["image"] == "https://example.com/photo.jpg"
    assert "email_verified_at" not in update_kwargs


@pytest.mark.asyncio
async def test_refresh_account_encrypts_tokens_and_persists_both_expiries() -> None:
    async def refresh_tokens(_oauth_client, token_set, _token_params):
        return {
            "access_token": "fresh-access-token",
            "refresh_token": token_set.refresh_token,
            "token_type": "Bearer",
            "scope": token_set.scope,
            "expires_in": 3600,
            "refresh_token_expires_in": 86400,
            "id_token": "fresh-id-token",
        }

    plugin = _build_plugin(encrypt_tokens=True, refresh_tokens=refresh_tokens)
    record = _build_account()

    async def update_oauth_account_by_id(_account_id: UUID, **updates: AccountTokenValue) -> StubOAuthAccount:
        access_token = _string_or_none(updates.get("access_token"))
        refresh_token = _string_or_none(updates.get("refresh_token"))
        token_type = _string_or_none(updates.get("token_type"))
        scope = _string_or_none(updates.get("scope"))
        id_token = _string_or_none(updates.get("id_token"))
        access_token_expires_at = _datetime_or_none(updates.get("access_token_expires_at"))
        refresh_token_expires_at = _datetime_or_none(updates.get("refresh_token_expires_at"))
        if access_token_expires_at is None or refresh_token_expires_at is None:
            msg = "expected token expirations"
            raise AssertionError(msg)
        return _build_account(
            id=record.id,
            individual_id=record.individual_id,
            provider_account_id=record.provider_account_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=access_token_expires_at.replace(tzinfo=None),
            refresh_token_expires_at=refresh_token_expires_at.replace(tzinfo=None),
            token_type=token_type,
            scope=scope,
            id_token=id_token,
        )

    client_dependency = _build_client()
    _set_async_return(client_dependency.get_oauth_account_for_individual_mock, record)
    client_dependency.update_oauth_account_by_id_mock.side_effect = update_oauth_account_by_id

    result = await plugin.refresh_account(
        client_dependency,
        individual_id=record.individual_id,
        provider_account_id=record.provider_account_id,
    )

    update_kwargs = client_dependency.update_oauth_account_by_id_mock.await_args.kwargs
    assert update_kwargs["access_token"].startswith("enc:v1:")
    assert update_kwargs["refresh_token"].startswith("enc:v1:")
    assert update_kwargs["id_token"].startswith("enc:v1:")
    assert update_kwargs["access_token_expires_at"] is not None
    assert update_kwargs["refresh_token_expires_at"] is not None
    assert result.access_token == "fresh-access-token"
    assert result.id_token == "fresh-id-token"


@pytest.mark.asyncio
async def test_token_set_and_get_access_token_auto_refresh_expired_tokens(monkeypatch) -> None:
    plugin = _build_plugin()
    oauth_client = plugin.client_type(plugin=plugin, client=_build_client())
    expired = _linked_account(
        access_token_expires_at=datetime.now(UTC) - timedelta(seconds=10),
        access_token="expired-token",
    )
    refreshed = _linked_account(
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
        access_token="fresh-token",
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    monkeypatch.setattr(plugin._flow, "_get_linked_account", AsyncMock(return_value=expired))
    refresh_account_mock = AsyncMock(return_value=refreshed)
    monkeypatch.setattr(plugin._flow, "refresh_account", refresh_account_mock)

    token_set = await oauth_client.token_set(
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
    )
    token = await oauth_client.get_access_token(
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
    )

    assert token_set.access_token == "fresh-token"
    assert token == "fresh-token"
    assert token_set.access_token_expires_at == refreshed.access_token_expires_at
    assert refresh_account_mock.await_count == 2


@pytest.mark.asyncio
async def test_account_info_fetches_provider_profile_with_custom_userinfo() -> None:
    async def get_userinfo(_oauth_client, _token_set, _metadata):
        return {
            "sub": "provider-account-9",
            "email": "profile@example.com",
            "email_verified": True,
            "name": "Profile Person",
            "picture": "https://example.com/avatar.jpg",
        }

    plugin = _build_plugin(get_userinfo=get_userinfo)
    record = _build_account(provider_account_id="provider-account-9")
    client_dependency = _build_client()
    _set_async_return(client_dependency.get_oauth_account_for_individual_mock, record)

    profile = await plugin.account_info(
        client_dependency,
        individual_id=record.individual_id,
        provider_account_id=record.provider_account_id,
    )

    assert profile is not None
    assert profile.provider_account_id == "provider-account-9"
    assert profile.email == "profile@example.com"
    assert profile.email_verified is True


@pytest.mark.asyncio
async def test_unlink_account_uses_provider_account_id() -> None:
    plugin = _build_plugin()
    client_dependency = _build_client()
    _set_async_return(client_dependency.unlink_oauth_account_mock, True)
    individual_id = uuid4()

    result = await plugin.unlink_account(
        client_dependency,
        individual_id=individual_id,
        provider_account_id="provider-account-1",
    )

    assert result is True
    client_dependency.unlink_oauth_account_mock.assert_awaited_once_with(
        individual_id=individual_id,
        provider="acme",
        provider_account_id="provider-account-1",
    )


@pytest.mark.asyncio
async def test_list_accounts_supports_multiple_same_provider_accounts() -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    first = _build_account(individual_id=individual_id, provider_account_id="provider-account-1")
    second = _build_account(individual_id=individual_id, provider_account_id="provider-account-2")
    client_dependency = _build_client()
    _set_async_return(client_dependency.list_oauth_accounts_mock, [first, second])

    accounts = await plugin.list_accounts(client_dependency, individual_id=individual_id)

    assert [account.provider_account_id for account in accounts] == ["provider-account-1", "provider-account-2"]
