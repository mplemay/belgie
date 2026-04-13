"""Reference implementation of authentication models."""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.mixins import (
    AccountMixin,
    IndividualMixin,
    OAuthAccountMixin,
    OAuthServerAccessTokenMixin,
    OAuthServerAuthorizationCodeMixin,
    OAuthServerAuthorizationStateMixin,
    OAuthServerClientMixin,
    OAuthServerConsentMixin,
    OAuthServerRefreshTokenMixin,
    OAuthStateMixin,
    SessionMixin,
)


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Individual(IndividualMixin, Account):
    custom_field: Mapped[str | None] = mapped_column(Text, default=None)


class OAuthAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


class OAuthServerClient(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthServerClientMixin):
    pass


class OAuthServerAuthorizationState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthServerAuthorizationStateMixin):
    pass


class OAuthServerAuthorizationCode(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthServerAuthorizationCodeMixin):
    pass


class OAuthServerAccessToken(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthServerAccessTokenMixin):
    pass


class OAuthServerRefreshToken(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthServerRefreshTokenMixin):
    pass


class OAuthServerConsent(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthServerConsentMixin):
    pass


__all__ = [
    "Account",
    "Individual",
    "OAuthAccount",
    "OAuthServerAccessToken",
    "OAuthServerAuthorizationCode",
    "OAuthServerAuthorizationState",
    "OAuthServerClient",
    "OAuthServerConsent",
    "OAuthServerRefreshToken",
    "OAuthState",
    "Session",
]
