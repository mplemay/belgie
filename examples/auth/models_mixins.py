from sqlalchemy.orm import DeclarativeBase

from belgie.auth.adapters.alchemy.mixins import (
    AccountMixin,
    OAuthStateMixin,
    PrimaryKeyMixin,
    SessionMixin,
    TimestampMixin,
    UserMixin,
)


class Base(DeclarativeBase):
    pass


class User(PrimaryKeyMixin, UserMixin, TimestampMixin, Base):
    __tablename__ = "user"


class Account(PrimaryKeyMixin, AccountMixin, TimestampMixin, Base):
    __tablename__ = "account"


class Session(PrimaryKeyMixin, SessionMixin, TimestampMixin, Base):
    __tablename__ = "session"


class OAuthState(PrimaryKeyMixin, OAuthStateMixin, TimestampMixin, Base):
    __tablename__ = "oauth_state"
