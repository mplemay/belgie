from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from sqlalchemy import JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie import Belgie, BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie.alchemy import AlchemyAdapter, Base, DatabaseSettings, DateTimeUTC, PrimaryKeyMixin, TimestampMixin
from belgie.mcp import build_belgie_oauth_auth
from belgie.oauth import OAuthPlugin, OAuthSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID


class User(Base, PrimaryKeyMixin, TimestampMixin):
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


class Account(Base, PrimaryKeyMixin, TimestampMixin):
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


class Session(Base, PrimaryKeyMixin, TimestampMixin):
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


class OAuthState(Base, PrimaryKeyMixin, TimestampMixin):
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
        await conn.run_sync(Base.metadata.create_all)
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
    providers=None,
)

oauth_settings = OAuthSettings(
    issuer_url="http://localhost:8000/auth/oauth",
    route_prefix="/oauth",
    client_id="demo-client",
    client_secret="demo-secret",  # noqa: S106
    redirect_uris=["http://localhost:8000/client/callback"],
    default_scope="user",
)

belgie.add_plugin(OAuthPlugin, oauth_settings)
app.include_router(belgie.router())

mcp_bundle = build_belgie_oauth_auth(
    oauth_settings,
    server_url="http://localhost:8000/mcp",
    oauth_strict=False,
)

mcp_server = MCPServer(
    name="Belgie MCP",
    instructions="MCP server protected by belgie-oauth",
    token_verifier=mcp_bundle.token_verifier,
    auth=mcp_bundle.auth,
)


@mcp_server.tool()
async def get_time() -> dict[str, Any]:
    now = datetime.datetime.now(datetime.UTC)
    return {
        "current_time": now.isoformat(),
        "timezone": "UTC",
        "timestamp": now.timestamp(),
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


mcp_app = mcp_server.streamable_http_app(
    streamable_http_path="/",
    host="localhost",
)
app.mount("/mcp", mcp_app)


@app.get("/")
async def home() -> dict[str, str]:
    return {
        "message": "belgie oauth + mcp example",
        "metadata": "/auth/oauth/.well-known/oauth-authorization-server",
        "authorize": "/auth/oauth/authorize",
        "login": "/auth/oauth/login",
        "token": "/auth/oauth/token",
        "introspect": "/auth/oauth/introspect",
        "client_callback": "/client/callback",
        "mcp": "/mcp",
    }


@app.get("/client/callback")
async def client_callback(
    code: str | None = None,
    state: str | None = None,
) -> dict[str, str | None]:
    return {
        "code": code,
        "state": state,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
