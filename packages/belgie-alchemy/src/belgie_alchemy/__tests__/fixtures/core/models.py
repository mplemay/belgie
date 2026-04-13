"""Test models for alchemy tests."""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy.orm import Mapped, mapped_column

from belgie_alchemy.core.mixins import AccountMixin, IndividualMixin, OAuthAccountMixin, OAuthStateMixin, SessionMixin
from belgie_alchemy.oauth_server import (
    OAuthServerAccessTokenMixin,
    OAuthServerAuthorizationCodeMixin,
    OAuthServerAuthorizationStateMixin,
    OAuthServerClientMixin,
    OAuthServerConsentMixin,
    OAuthServerRefreshTokenMixin,
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
