from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from brussels.types import DateTimeUTC
from sqlalchemy import Index, Text
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, declared_attr, mapped_column


@declarative_mixin
class StripeUserMixin(MappedAsDataclass):
    @declared_attr
    def stripe_customer_id(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, index=True, kw_only=True)


@declarative_mixin
class StripeOrganizationMixin(MappedAsDataclass):
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
    def reference_id(self) -> Mapped[UUID]:
        return mapped_column(index=True, kw_only=True)

    @declared_attr
    def customer_type(self) -> Mapped[str]:
        return mapped_column(Text, index=True, kw_only=True)

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

    @declared_attr.directive
    def __table_args__(self) -> tuple[Index, Index]:
        return (
            Index("ix_subscription_reference_customer_type", self.reference_id, self.customer_type),
            Index("ix_subscription_reference_customer_type_status", self.reference_id, self.customer_type, self.status),
        )


__all__ = [
    "StripeOrganizationMixin",
    "StripeSubscriptionMixin",
    "StripeUserMixin",
]
