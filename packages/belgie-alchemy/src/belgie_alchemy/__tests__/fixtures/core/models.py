"""Test models for alchemy tests.

Defines concrete auth models for testing. These mirror the examples in
examples/alchemy/auth_models.py and demonstrate how users would define
their own models.
"""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy.orm import Mapped, mapped_column

from belgie_alchemy.core.mixins import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin


class User(DataclassBase, PrimaryKeyMixin, TimestampMixin, UserMixin):
    """Test User model."""

    custom_field: Mapped[str | None] = mapped_column(default=None)


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    """Test Account model."""


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    """Test Session model."""


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    """Test OAuthState model."""
