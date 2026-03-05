from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from belgie_core.core.belgie import Belgie
from belgie_core.core.settings import BelgieSettings, CookieSettings, SessionSettings, URLSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from belgie_alchemy.__tests__.fixtures.core.database import get_test_engine, get_test_session_factory
from belgie_alchemy.__tests__.fixtures.core.models import Account, OAuthState, Session, User
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.core.settings import SqliteSettings

PACKAGES_ROOT = Path(__file__).resolve().parents[7]
OAUTH_SRC = PACKAGES_ROOT / "belgie-oauth-server" / "src"
if str(OAUTH_SRC) not in sys.path:
    sys.path.insert(0, str(OAUTH_SRC))

from belgie_oauth_server import OAuthResource, OAuthServer, OAuthServerPlugin  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


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


@pytest_asyncio.fixture
async def database(sqlite_database: str):
    database = SqliteSettings(database=sqlite_database)
    yield database
    await database.engine.dispose()


@pytest_asyncio.fixture
async def adapter():
    adapter = BelgieAdapter(
        user=User,
        account=Account,
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
    database: SqliteSettings,
    db_session: AsyncSession,
) -> Belgie:
    _ = db_session
    return Belgie(settings=belgie_settings, adapter=adapter, database=database)


@pytest.fixture
def oauth_settings() -> OAuthServer:
    return OAuthServer(
        base_url="http://testserver",
        prefix="/oauth",
        login_url="/login/google",
        signup_url="/signup",
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        redirect_uris=["http://testserver/callback"],
        default_scope="user",
        resources=[OAuthResource(prefix="/mcp", scopes=["user"])],
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
def create_user_session():
    async def _create(belgie: Belgie, db_session: AsyncSession, email: str) -> str:
        user = await belgie.adapter.create_user(db_session, email=email)
        session = await belgie.session_manager.create_session(db_session, user_id=user.id)
        return str(session.id)

    return _create
