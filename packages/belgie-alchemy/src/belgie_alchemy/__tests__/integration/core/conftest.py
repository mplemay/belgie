"""Shared fixtures for integration tests that require SQLAlchemy."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, status
from fastapi.responses import RedirectResponse

from belgie_alchemy.__tests__.fixtures.core.database import get_test_engine, get_test_session_factory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from belgie_core.core.belgie import Belgie
    from belgie_oauth.plugin import GoogleOAuthClient
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

PACKAGES_ROOT = Path(__file__).resolve().parents[7]
OAUTH_CLIENT_SRC = PACKAGES_ROOT / "belgie-oauth" / "src"
if str(OAUTH_CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(OAUTH_CLIENT_SRC))

from belgie_oauth import GoogleOAuthClient, GoogleOAuthPlugin  # noqa: E402


@pytest_asyncio.fixture
async def db_engine(sqlite_database: str) -> AsyncGenerator[AsyncEngine, None]:
    engine = await get_test_engine(sqlite_database)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return await get_test_session_factory(db_engine)


@pytest_asyncio.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def add_google_login_route():
    def apply(app: FastAPI, auth: Belgie) -> None:
        google_plugin = next(plugin for plugin in auth.plugins if isinstance(plugin, GoogleOAuthPlugin))

        @app.get("/login/google")
        async def login_google(
            google: GoogleOAuthClient = Depends(google_plugin),
            return_to: str | None = None,
        ) -> RedirectResponse:
            auth_url = await google.signin_url(return_to=return_to)
            return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)

    return apply
