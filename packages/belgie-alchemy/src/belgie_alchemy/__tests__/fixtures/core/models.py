"""Test models for alchemy tests."""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy.orm import Mapped, mapped_column

from belgie_alchemy.core.mixins import AccountMixin, IndividualMixin, OAuthAccountMixin, OAuthStateMixin, SessionMixin
from belgie_alchemy.oauth_server import (
    OAuthAccessTokenMixin,
    OAuthAuthorizationCodeMixin,
    OAuthAuthorizationStateMixin,
    OAuthClientMixin,
    OAuthConsentMixin,
    OAuthRefreshTokenMixin,
)
from belgie_alchemy.stripe.mixins import StripeAccountMixin


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin, StripeAccountMixin):
    pass


class Individual(IndividualMixin, Account):
    custom_field: Mapped[str | None] = mapped_column(default=None)


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
