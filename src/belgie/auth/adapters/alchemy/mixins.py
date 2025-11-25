from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column
from sqlalchemy.sql.functions import FunctionElement

if TYPE_CHECKING:
    from sqlalchemy.sql.compiler import SQLCompiler


class ServerSideUUID(FunctionElement):
    """Dialect-aware server UUID generator."""

    type = Uuid()


@compiles(ServerSideUUID, "postgresql")
def _pg_server_uuid(_element: FunctionElement, _compiler: SQLCompiler, **_kw: object) -> str:
    return "gen_random_uuid()"


@compiles(ServerSideUUID, "timescaledb")
def _ts_server_uuid(
    _element: FunctionElement,
    _compiler: SQLCompiler,
    **_kw: object,
) -> str:  # TimescaleDB uses PostgreSQL functions
    return "gen_random_uuid()"


@compiles(ServerSideUUID, "mysql")
@compiles(ServerSideUUID, "mariadb")
def _mysql_server_uuid(_element: FunctionElement, _compiler: SQLCompiler, **_kw: object) -> str:
    return "uuid()"


@compiles(ServerSideUUID)
def _default_server_uuid(_element: FunctionElement, _compiler: SQLCompiler, **_kw: object) -> str:
    # Fallback (e.g., SQLite) - results in NULL server default; client default fills in
    return "NULL"


@declarative_mixin
class PrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        unique=True,
        index=True,
        default=uuid4,  # client-side fallback for dialects without server UUIDs
        server_default=ServerSideUUID(),  # server-side where supported, no-op elsewhere
    )


@declarative_mixin
class TimestampMixin:
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


@declarative_mixin
class UserMixin:
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified: Mapped[bool] = mapped_column(default=False)


@declarative_mixin
class AccountMixin:
    @declared_attr.directive
    def user_id(cls) -> Mapped[UUID]:  # noqa: N805
        return mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)

    provider: Mapped[str] = mapped_column(String(50), index=True)
    provider_account_id: Mapped[str] = mapped_column(String(255), index=True)
    access_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=True)
    token_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(500), nullable=True)


@declarative_mixin
class SessionMixin:
    @declared_attr.directive
    def user_id(cls) -> Mapped[UUID]:  # noqa: N805
        return mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)

    expires_at: Mapped[Any] = mapped_column(DateTime(timezone=True), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)


@declarative_mixin
class OAuthStateMixin:
    state: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    code_verifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    expires_at: Mapped[Any] = mapped_column(DateTime(timezone=True), index=True)


__all__ = [
    "AccountMixin",
    "OAuthStateMixin",
    "PrimaryKeyMixin",
    "SessionMixin",
    "TimestampMixin",
    "UserMixin",
]
