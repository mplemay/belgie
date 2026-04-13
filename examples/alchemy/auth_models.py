"""Reference implementation of authentication models."""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.mixins import (
    AccountMixin,
    IndividualMixin,
    OAuthAccessTokenMixin,
    OAuthAccountMixin,
    OAuthAuthorizationCodeMixin,
    OAuthAuthorizationStateMixin,
    OAuthClientMixin,
    OAuthConsentMixin,
    OAuthRefreshTokenMixin,
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


class OAuthClient(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthClientMixin):
    pass


class OAuthAuthorizationState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAuthorizationStateMixin):
    pass


class OAuthAuthorizationCode(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAuthorizationCodeMixin):
    pass


class OAuthAccessToken(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccessTokenMixin):
    pass


class OAuthRefreshToken(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthRefreshTokenMixin):
    pass


class OAuthConsent(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthConsentMixin):
    pass


__all__ = [
    "Account",
    "Individual",
    "OAuthAccessToken",
    "OAuthAccount",
    "OAuthAuthorizationCode",
    "OAuthAuthorizationState",
    "OAuthClient",
    "OAuthConsent",
    "OAuthRefreshToken",
    "OAuthState",
    "Session",
]
