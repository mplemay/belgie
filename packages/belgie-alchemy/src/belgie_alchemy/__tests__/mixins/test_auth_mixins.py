from __future__ import annotations

from uuid import UUID  # noqa: TC003

from brussels.base import DataclassBase
from brussels.types import DateTimeUTC, Json
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie_alchemy import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin
from belgie_alchemy.__tests__.fixtures.models import Account, OAuthState, Session, User


def test_auth_mixins_exported() -> None:
    assert UserMixin is not None
    assert AccountMixin is not None
    assert SessionMixin is not None
    assert OAuthStateMixin is not None


def test_fixture_models_use_auth_mixins() -> None:
    assert issubclass(User, UserMixin)
    assert issubclass(Account, AccountMixin)
    assert issubclass(Session, SessionMixin)
    assert issubclass(OAuthState, OAuthStateMixin)


def test_default_tablenames() -> None:
    assert UserMixin.__tablename__ == "user"
    assert AccountMixin.__tablename__ == "account"
    assert SessionMixin.__tablename__ == "session"
    assert OAuthStateMixin.__tablename__ == "oauth_state"


def test_user_mixin_defaults() -> None:
    email_column = User.__table__.c.email
    assert email_column.unique
    assert email_column.index

    scopes_column = User.__table__.c.scopes
    assert isinstance(scopes_column.type, type(Json))

    email_verified_column = User.__table__.c.email_verified
    assert email_verified_column.default is not None
    assert email_verified_column.default.arg is False

    assert User.accounts.property.back_populates == "user"
    assert User.sessions.property.back_populates == "user"
    assert User.oauth_states.property.back_populates == "user"


def test_account_session_oauthstate_mixin_defaults() -> None:
    account_fk = next(iter(Account.__table__.c.user_id.foreign_keys))
    assert account_fk.target_fullname == "user.id"
    assert account_fk.ondelete == "cascade"
    assert account_fk.onupdate == "cascade"
    assert isinstance(Account.__table__.c.expires_at.type, DateTimeUTC)

    unique_constraints = [
        constraint for constraint in Account.__table__.constraints if isinstance(constraint, UniqueConstraint)
    ]
    assert any(
        constraint.name == "uq_accounts_provider_provider_account_id"
        and set(constraint.columns.keys()) == {"provider", "provider_account_id"}
        for constraint in unique_constraints
    )

    assert isinstance(Session.__table__.c.expires_at.type, DateTimeUTC)
    session_fk = next(iter(Session.__table__.c.user_id.foreign_keys))
    assert session_fk.target_fullname == "user.id"
    assert session_fk.ondelete == "cascade"
    assert session_fk.onupdate == "cascade"

    assert isinstance(OAuthState.__table__.c.expires_at.type, DateTimeUTC)
    oauth_state_fk = next(iter(OAuthState.__table__.c.user_id.foreign_keys))
    assert oauth_state_fk.target_fullname == "user.id"
    assert oauth_state_fk.ondelete == "set null"
    assert oauth_state_fk.onupdate == "cascade"


def test_mixins_support_relationship_and_tablename_overrides() -> None:
    class CustomUser(DataclassBase, UserMixin):
        __tablename__ = "custom_users"

        accounts: Mapped[list[CustomAccount]] = relationship(
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        sessions: Mapped[list[CustomSession]] = relationship(
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )
        oauth_states: Mapped[list[CustomOAuthState]] = relationship(
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )

    class CustomAccount(DataclassBase, AccountMixin):
        __tablename__ = "custom_accounts"

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey("custom_users.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
        )
        user: Mapped[CustomUser] = relationship(
            back_populates="accounts",
            lazy="selectin",
            init=False,
        )

    class CustomSession(DataclassBase, SessionMixin):
        __tablename__ = "custom_sessions"

        user_id: Mapped[UUID] = mapped_column(
            ForeignKey("custom_users.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
        )
        user: Mapped[CustomUser] = relationship(
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )

    class CustomOAuthState(DataclassBase, OAuthStateMixin):
        __tablename__ = "custom_oauth_states"

        user_id: Mapped[UUID | None] = mapped_column(
            ForeignKey("custom_users.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
        )
        user: Mapped[CustomUser | None] = relationship(
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )

    assert CustomUser.__table__.name == "custom_users"
    assert CustomAccount.__table__.name == "custom_accounts"
    assert CustomSession.__table__.name == "custom_sessions"
    assert CustomOAuthState.__table__.name == "custom_oauth_states"

    custom_account_fk = next(iter(CustomAccount.__table__.c.user_id.foreign_keys))
    assert custom_account_fk.target_fullname == "custom_users.id"

    custom_session_fk = next(iter(CustomSession.__table__.c.user_id.foreign_keys))
    assert custom_session_fk.target_fullname == "custom_users.id"

    custom_oauth_state_fk = next(iter(CustomOAuthState.__table__.c.user_id.foreign_keys))
    assert custom_oauth_state_fk.target_fullname == "custom_users.id"
