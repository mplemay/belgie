from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from brussels.types import DateTimeUTC
from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, declared_attr, mapped_column, relationship


@declarative_mixin
class StripeAccountMixin(MappedAsDataclass):
    @declared_attr
    def stripe_customer_id(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, index=True, kw_only=True)


@declarative_mixin
class StripeSubscriptionMixin(MappedAsDataclass):
    __tablename__ = "subscription"

    @declared_attr
    def plan(self) -> Mapped[str]:
        return mapped_column(Text, kw_only=True)

    @declared_attr
    def account_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("account.id", ondelete="cascade", onupdate="cascade"),
            index=True,
            kw_only=True,
        )

    @declared_attr
    def account(self) -> Mapped[object]:
        return relationship(
            "Account",
            lazy="selectin",
            init=False,
        )

    @declared_attr
    def stripe_customer_id(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, index=True, kw_only=True)

    @declared_attr
    def stripe_subscription_id(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, unique=True, index=True, kw_only=True)

    @declared_attr
    def status(self) -> Mapped[str]:
        return mapped_column(Text, default="incomplete", index=True, kw_only=True)

    @declared_attr
    def period_start(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def period_end(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def trial_start(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def trial_end(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def seats(self) -> Mapped[int | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def cancel_at_period_end(self) -> Mapped[bool]:
        return mapped_column(default=False, kw_only=True)

    @declared_attr
    def cancel_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def canceled_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def ended_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def billing_interval(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def stripe_schedule_id(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, unique=True, index=True, kw_only=True)

    @declared_attr.directive
    def __table_args__(self) -> tuple[Index, Index]:
        return (
            Index("ix_subscription_account", self.account_id),
            Index("ix_subscription_account_status", self.account_id, self.status),
        )


__all__ = [
    "StripeAccountMixin",
    "StripeSubscriptionMixin",
]
