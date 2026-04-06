from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID  # noqa: TC003

from belgie_proto.stripe import (
    StripeAccountProtocol,
    StripeBillingInterval,
    StripeSubscriptionProtocol,
    StripeSubscriptionStatus,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from stripe import Subscription


type JSONScalar = str | int | float | bool | None
type StripeAction = Literal[
    "billing-portal",
    "cancel-subscription",
    "list-subscription",
    "restore-subscription",
    "upgrade-subscription",
]


class StripePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    price_id: str | None = None
    lookup_key: str | None = None
    annual_price_id: str | None = None
    annual_lookup_key: str | None = None
    limits: dict[str, JSONScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_plan_source(self) -> Self:
        if not self.price_id and not self.lookup_key:
            msg = "stripe plan requires price_id or lookup_key"
            raise ValueError(msg)
        return self


class UpgradeSubscriptionRequest(BaseModel):
    plan: str
    annual: bool = False
    account_id: UUID | None = None
    success_url: str
    cancel_url: str
    return_url: str | None = None
    disable_redirect: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


class ListSubscriptionsRequest(BaseModel):
    account_id: UUID | None = None


class CancelSubscriptionRequest(BaseModel):
    account_id: UUID | None = None
    return_url: str
    disable_redirect: bool = False


class RestoreSubscriptionRequest(BaseModel):
    account_id: UUID | None = None


class BillingPortalRequest(BaseModel):
    account_id: UUID | None = None
    return_url: str | None = None
    disable_redirect: bool = False


class StripeRedirectResponse(BaseModel):
    url: str
    redirect: bool = True


class SubscriptionView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    plan: str
    account_id: UUID
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    status: StripeSubscriptionStatus
    period_start: datetime | None = None
    period_end: datetime | None = None
    cancel_at_period_end: bool
    cancel_at: datetime | None = None
    canceled_at: datetime | None = None
    ended_at: datetime | None = None
    billing_interval: StripeBillingInterval | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_subscription[T: StripeSubscriptionProtocol](cls, subscription: T) -> Self:
        return cls.model_validate(subscription)


@dataclass(slots=True, kw_only=True, frozen=True)
class AccountAuthorizationContext[AccountT, IndividualT, SessionT]:
    action: StripeAction
    account: AccountT
    individual: IndividualT
    session: SessionT


@dataclass(slots=True, kw_only=True, frozen=True)
class AccountCreateContext[AccountT]:
    account: AccountT
    stripe_customer_id: str
    metadata: dict[str, str]


@dataclass(slots=True, kw_only=True, frozen=True)
class CheckoutSessionContext[SubscriptionT, AccountT, IndividualT, SessionT]:
    account: AccountT
    plan: StripePlan
    subscription: SubscriptionT
    individual: IndividualT
    session: SessionT


@dataclass(slots=True, kw_only=True, frozen=True)
class SubscriptionEventContext[SubscriptionT, AccountT]:
    event_type: str
    plan: StripePlan | None
    raw_event: Subscription
    subscription: SubscriptionT
    account: AccountT


def account_type_label(account: StripeAccountProtocol) -> str:
    return account.account_type.value
