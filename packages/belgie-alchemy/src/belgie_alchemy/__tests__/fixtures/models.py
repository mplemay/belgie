"""Test models for alchemy tests.

Defines concrete auth models for testing. These mirror the examples in
examples/alchemy/auth_models.py and demonstrate how users would define
their own models.
"""

from __future__ import annotations

from brussels.base import DataclassBase
from sqlalchemy.orm import Mapped, mapped_column

from belgie_alchemy.mixins import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin


class User(DataclassBase, UserMixin):
    """Test User model."""

    custom_field: Mapped[str | None] = mapped_column(default=None)


class Account(DataclassBase, AccountMixin):
    """Test Account model."""


class Session(DataclassBase, SessionMixin):
    """Test Session model."""


class OAuthState(DataclassBase, OAuthStateMixin):
    """Test OAuthState model."""
