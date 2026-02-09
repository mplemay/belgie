from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID  # noqa: TC003

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from brussels.types import DateTimeUTC
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from mcp.server.mcpserver import MCPServer
from sqlalchemy import JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie import Belgie, BelgieClient, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import AlchemyAdapter, DatabaseSettings
from belgie.mcp import McpPlugin, McpPluginSettings, get_user_from_access_token
from belgie.oauth.server import OAuthResource, OAuthServerPlugin, OAuthServerSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class User(DataclassBase, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    name: Mapped[str | None] = mapped_column(default=None)
    image: Mapped[str | None] = mapped_column(default=None)
    scopes: Mapped[list[str] | None] = mapped_column(JSON, default=None)

    accounts: Mapped[list[Account]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        init=False,
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        init=False,
    )
    oauth_states: Mapped[list[OAuthState]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        init=False,
    )


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "accounts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text)
    provider_account_id: Mapped[str] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(default=None)
    refresh_token: Mapped[str | None] = mapped_column(default=None)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, default=None)
    token_type: Mapped[str | None] = mapped_column(default=None)
    scope: Mapped[str | None] = mapped_column(default=None)
    id_token: Mapped[str | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(
        back_populates="accounts",
        lazy="selectin",
        init=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_accounts_provider_provider_account_id",
        ),
    )


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC)
    ip_address: Mapped[str | None] = mapped_column(default=None)
    user_agent: Mapped[str | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(
        back_populates="sessions",
        lazy="selectin",
        init=False,
    )


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(unique=True, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC)
    code_verifier: Mapped[str | None] = mapped_column(default=None)
    redirect_url: Mapped[str | None] = mapped_column(default=None)

    user: Mapped[User] | None = relationship(
        back_populates="oauth_states",
        lazy="selectin",
        init=False,
    )


DB_PATH = "./belgie_mcp_example.db"


db_settings = DatabaseSettings(
    dialect={"type": "sqlite", "database": DB_PATH, "echo": True},
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with db_settings.engine.begin() as conn:
        await conn.run_sync(DataclassBase.metadata.create_all)

    async with mcp_server.session_manager.run():
        yield

    await db_settings.engine.dispose()


app = FastAPI(title="Belgie MCP OAuth Example", lifespan=lifespan)

settings = BelgieSettings(
    secret="change-me",  # noqa: S106
    base_url="http://localhost:8000",
    session=SessionSettings(
        max_age=3600 * 24,
        update_age=3600,
    ),
    cookie=CookieSettings(
        secure=False,
        http_only=True,
        same_site="lax",
    ),
    urls=URLSettings(
        signin_redirect="/",
        signout_redirect="/",
    ),
)

adapter = AlchemyAdapter(
    user=User,
    account=Account,
    session=Session,
    oauth_state=OAuthState,
)

belgie = Belgie(
    settings=settings,
    adapter=adapter,
    db=db_settings,
)

oauth_settings = OAuthServerSettings(
    base_url=settings.base_url,
    prefix="/oauth",
    client_id="demo-client",
    client_secret="demo-secret",  # noqa: S106
    redirect_uris=["http://localhost:3030/callback"],
    default_scope="user",
    login_url="/login",
    resources=[OAuthResource(prefix="/mcp", scopes=["user"])],
)

_ = belgie.add_plugin(OAuthServerPlugin, oauth_settings)
mcp_plugin = belgie.add_plugin(
    McpPlugin,
    McpPluginSettings(
        oauth_settings=oauth_settings,
        base_url=settings.base_url,
    ),
)

mcp_server = MCPServer(
    name="Belgie MCP",
    instructions="MCP server protected by belgie-oauth",
    token_verifier=mcp_plugin.token_verifier,
    auth=mcp_plugin.auth,
)

app.include_router(belgie.router)

mcp_app = mcp_server.streamable_http_app(
    streamable_http_path="/",
    host="localhost",
)
app.mount("/mcp", mcp_app)


@mcp_server.tool()
async def get_time() -> dict[str, Any]:
    user = await get_user_from_access_token(belgie)
    now = datetime.datetime.now(datetime.UTC)
    return {
        "user_id": str(user.id) if user else None,
        "user_email": user.email if user else None,
        "current_time": now.isoformat(),
        "timezone": "UTC",
        "timestamp": now.timestamp(),
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/login")
async def login(
    request: Request,
    client: Annotated[BelgieClient, Depends(belgie)],
    return_to: str | None = None,
) -> RedirectResponse:
    response = RedirectResponse(url=return_to or "/", status_code=302)
    _user, session = await client.sign_up(
        "dev@example.com",
        name="Dev User",
        request=request,
    )
    return client.create_session_cookie(session, response)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
