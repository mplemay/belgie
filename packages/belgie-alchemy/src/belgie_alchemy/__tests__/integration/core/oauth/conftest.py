from __future__ import annotations

import base64
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from belgie_core.core.belgie import Belgie
from belgie_core.core.settings import BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie_oauth_server.models import OAuthServerClientInformationFull, OAuthServerClientMetadata
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from belgie_alchemy.__tests__.fixtures.core.database import get_test_engine, get_test_session_factory
from belgie_alchemy.__tests__.fixtures.core.models import (
    Account,
    Individual,
    OAuthAccount,
    OAuthServerAccessToken,
    OAuthServerAuthorizationCode,
    OAuthServerAuthorizationState,
    OAuthServerClient,
    OAuthServerConsent,
    OAuthServerRefreshToken,
    OAuthState,
    Session,
)
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.oauth_server import OAuthServerAdapter

PACKAGES_ROOT = Path(__file__).resolve().parents[7]
OAUTH_SRC = PACKAGES_ROOT / "belgie-oauth-server" / "src"
if str(OAUTH_SRC) not in sys.path:
    sys.path.insert(0, str(OAUTH_SRC))

from belgie_oauth_server import OAuthServer, OAuthServerPlugin, OAuthServerResource  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

DEFAULT_TEST_TOKEN_ENDPOINT_AUTH_METHOD = "client_secret_post"  # noqa: S105


@pytest_asyncio.fixture
async def db_engine(sqlite_database: str) -> AsyncEngine:
    engine = await get_test_engine(sqlite_database)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return await get_test_session_factory(db_engine)


@pytest_asyncio.fixture
async def db_session(db_session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def database(
    db_session_factory: async_sessionmaker[AsyncSession],
):
    async def get_db():
        async with db_session_factory() as session:
            yield session

    return get_db


@pytest_asyncio.fixture
async def adapter():
    adapter = BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    )
    yield adapter


@pytest.fixture
def belgie_settings() -> BelgieSettings:
    return BelgieSettings(
        secret="test-secret-key",
        base_url="http://testserver",
        session=SessionSettings(
            max_age=3600,
            update_age=900,
        ),
        cookie=CookieSettings(
            name="belgie_session",
            secure=False,
            http_only=True,
            same_site="lax",
        ),
        urls=URLSettings(
            signin_redirect="/dashboard",
            signout_redirect="/",
        ),
    )


@pytest.fixture
def belgie_instance(
    belgie_settings: BelgieSettings,
    adapter: BelgieAdapter,
    database,
    db_session: AsyncSession,
) -> Belgie:
    _ = db_session
    return Belgie(settings=belgie_settings, adapter=adapter, database=database)


@pytest.fixture
def oauth_settings() -> OAuthServer:
    oauth_adapter = OAuthServerAdapter(
        oauth_client=OAuthServerClient,
        oauth_authorization_state=OAuthServerAuthorizationState,
        oauth_authorization_code=OAuthServerAuthorizationCode,
        oauth_access_token=OAuthServerAccessToken,
        oauth_refresh_token=OAuthServerRefreshToken,
        oauth_consent=OAuthServerConsent,
    )
    return OAuthServer(
        adapter=oauth_adapter,
        base_url="http://testserver",
        prefix="/oauth",
        login_url="/login/google",
        signup_url="/signup",
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        redirect_uris=["http://testserver/callback"],
        default_scope="user",
        resources=[OAuthServerResource(prefix="/mcp", scopes=["user"])],
    )


@pytest.fixture
def oauth_plugin(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> OAuthServerPlugin:
    return belgie_instance.add_plugin(oauth_settings)


@pytest.fixture
def app(belgie_instance: Belgie, oauth_plugin: OAuthServerPlugin) -> FastAPI:
    _ = oauth_plugin
    app = FastAPI()
    app.include_router(belgie_instance.router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as client:
        yield client


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await transport.aclose()


@pytest.fixture
def basic_auth_header():
    def _build(client_id: str, client_secret: str) -> str:
        raw = f"{client_id}:{client_secret}".encode()
        return f"Basic {base64.b64encode(raw).decode('utf-8')}"

    return _build


@pytest.fixture
def update_static_client(oauth_plugin: OAuthServerPlugin):
    def _update(**updates: object) -> OAuthServerClientInformationFull:
        assert oauth_plugin._provider is not None
        oauth_plugin._provider.static_client = oauth_plugin._provider.static_client.model_copy(update=updates)
        return oauth_plugin._provider.static_client

    return _update


@pytest_asyncio.fixture
async def register_dynamic_client(oauth_plugin: OAuthServerPlugin, db_session: AsyncSession):
    async def _register(**metadata: object) -> OAuthServerClientInformationFull:
        assert oauth_plugin._provider is not None
        client_metadata = OAuthServerClientMetadata.model_validate(metadata)
        return await oauth_plugin._provider.register_client(client_metadata, db=db_session)

    return _register


@pytest_asyncio.fixture
async def seed_client(oauth_settings: OAuthServer, db_session: AsyncSession):
    async def _seed(
        *,
        client_id: str,
        client_secret: str | None = None,
        client_secret_hash: str | None = None,
        redirect_uris: list[str] | None = None,
        post_logout_redirect_uris: list[str] | None = None,
        token_endpoint_auth_method: str | None = None,
        grant_types: list[str] | None = None,
        response_types: list[str] | None = None,
        scope: str | None = None,
        client_type: str | None = None,
        subject_type: str | None = "public",
        require_pkce: bool | None = True,
        enable_end_session: bool | None = None,
        client_id_issued_at: int | None = None,
        client_secret_expires_at: int | None = 0,
        individual_id: str | None = None,
    ):
        client = await oauth_settings.adapter.create_client(
            db_session,
            client_id=client_id,
            client_secret=client_secret,
            client_secret_hash=client_secret_hash,
            redirect_uris=[str(uri) for uri in (redirect_uris or ["http://testserver/callback"])],
            post_logout_redirect_uris=(
                None if post_logout_redirect_uris is None else [str(uri) for uri in post_logout_redirect_uris]
            ),
            token_endpoint_auth_method=(token_endpoint_auth_method or DEFAULT_TEST_TOKEN_ENDPOINT_AUTH_METHOD),  # type: ignore[arg-type]
            grant_types=list(grant_types or ["authorization_code", "refresh_token"]),
            response_types=list(response_types or ["code"]),
            scope=scope,
            client_name=None,
            client_uri=None,
            logo_uri=None,
            contacts=None,
            tos_uri=None,
            policy_uri=None,
            jwks_uri=None,
            jwks=None,
            software_id=None,
            software_version=None,
            software_statement=None,
            type=client_type,  # type: ignore[arg-type]
            subject_type=subject_type,  # type: ignore[arg-type]
            require_pkce=require_pkce,
            enable_end_session=enable_end_session,
            client_id_issued_at=client_id_issued_at,
            client_secret_expires_at=client_secret_expires_at,
            individual_id=None if individual_id is None else UUID(individual_id),
        )
        await db_session.commit()
        await db_session.refresh(client)
        return client

    return _seed


@pytest_asyncio.fixture
async def seed_access_token(oauth_plugin: OAuthServerPlugin, oauth_settings: OAuthServer, db_session: AsyncSession):
    async def _seed(
        *,
        token: str,
        client_id: str | None = None,
        scopes: list[str] | None = None,
        resource: str | list[str] | None = None,
        refresh_token_id: UUID | None = None,
        individual_id: str | None = None,
        session_id: str | None = None,
        created_at: int | None = None,
        expires_at: int | None = None,
    ):
        assert oauth_plugin._provider is not None
        record = await oauth_settings.adapter.create_access_token(
            db_session,
            token_hash=oauth_plugin._provider._hash_value(token),
            client_id=client_id or oauth_settings.client_id,
            scopes=list(scopes or [oauth_settings.default_scope]),
            resource=resource,
            refresh_token_id=refresh_token_id,
            individual_id=None if individual_id is None else UUID(individual_id),
            session_id=None if session_id is None else UUID(session_id),
            expires_at=datetime.fromtimestamp(expires_at, UTC)
            if expires_at is not None
            else datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        await db_session.refresh(record)
        if created_at is not None:
            record.created_at = datetime.fromtimestamp(created_at, UTC)
            await db_session.commit()
            await db_session.refresh(record)
        return record

    return _seed


@pytest_asyncio.fixture
async def seed_refresh_token(oauth_plugin: OAuthServerPlugin, oauth_settings: OAuthServer, db_session: AsyncSession):
    async def _seed(
        *,
        token: str,
        client_id: str | None = None,
        scopes: list[str] | None = None,
        resource: str | None = None,
        individual_id: str | None = None,
        session_id: str | None = None,
        created_at: int | None = None,
        expires_at: int | None = None,
        revoked_at: int | None = None,
    ):
        assert oauth_plugin._provider is not None
        record = await oauth_settings.adapter.create_refresh_token(
            db_session,
            token_hash=oauth_plugin._provider._hash_value(token),
            client_id=client_id or oauth_settings.client_id,
            scopes=list(scopes or [oauth_settings.default_scope]),
            resource=resource,
            individual_id=None if individual_id is None else UUID(individual_id),
            session_id=None if session_id is None else UUID(session_id),
            expires_at=datetime.fromtimestamp(expires_at, UTC)
            if expires_at is not None
            else datetime.now(UTC) + timedelta(hours=1),
        )
        await db_session.commit()
        await db_session.refresh(record)
        if created_at is not None:
            record.created_at = datetime.fromtimestamp(created_at, UTC)
        if revoked_at is not None:
            record.revoked_at = datetime.fromtimestamp(revoked_at, UTC)
        if created_at is not None or revoked_at is not None:
            await db_session.commit()
            await db_session.refresh(record)
        return record

    return _seed


@pytest.fixture
def create_individual_session():
    async def _create(belgie: Belgie, db_session: AsyncSession, email: str) -> str:
        user = await belgie.adapter.create_individual(db_session, email=email)
        session = await belgie.session_manager.create_session(db_session, individual_id=user.id)
        return str(session.id)

    return _create
