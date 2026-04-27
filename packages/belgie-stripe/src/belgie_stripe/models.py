from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID  # noqa: TC003

from belgie_proto.core.json import JSONObject  # noqa: TC002
from belgie_proto.stripe import (
    StripeAccountProtocol,
    StripeBillingInterval,
    StripeSubscriptionProtocol,
    StripeSubscriptionStatus,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from stripe.params import checkout  # noqa: TC002

if TYPE_CHECKING:
    from stripe import Subscription
    from stripe.checkout import Session as CheckoutSession


type MaybeAwaitable[T] = T | Awaitable[T]
type StripeAction = Literal[
    "billing-portal",
    "cancel-subscription",
    "list-subscription",
    "restore-subscription",
    "upgrade-subscription",
]
type StripeProrationBehavior = Literal["always_invoice", "create_prorations", "none"]
type CheckoutSessionLocale = Literal[
    "auto",
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "en-GB",
    "es",
    "es-419",
    "et",
    "fi",
    "fil",
    "fr",
    "fr-CA",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "lt",
    "lv",
    "ms",
    "mt",
    "nb",
    "nl",
    "pl",
    "pt",
    "pt-BR",
    "ro",
    "ru",
    "sk",
    "sl",
    "sv",
    "th",
    "tr",
    "vi",
    "zh",
    "zh-HK",
    "zh-TW",
]
type BillingPortalLocale = (
    CheckoutSessionLocale
    | Literal[
        "en-AU",
        "en-CA",
        "en-IE",
        "en-IN",
        "en-NZ",
        "en-SG",
    ]
)
type StripeSubscriptionLocale = CheckoutSessionLocale | BillingPortalLocale


class StripeFreeTrial(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    days: int = Field(ge=1)
    on_trial_start: (
        Callable[
            [SubscriptionEventContext[StripeSubscriptionProtocol, StripeAccountProtocol]],
            MaybeAwaitable[None],
        ]
        | None
    ) = Field(default=None, exclude=True)
    on_trial_end: (
        Callable[
            [SubscriptionEventContext[StripeSubscriptionProtocol, StripeAccountProtocol]],
            MaybeAwaitable[None],
        ]
        | None
    ) = Field(default=None, exclude=True)
    on_trial_expired: (
        Callable[
            [SubscriptionEventContext[StripeSubscriptionProtocol, StripeAccountProtocol]],
            MaybeAwaitable[None],
        ]
        | None
    ) = Field(default=None, exclude=True)


class StripePlan(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    price_id: str | None = None
    lookup_key: str | None = None
    annual_price_id: str | None = None
    annual_lookup_key: str | None = None
    seat_price_id: str | None = None
    line_items: list[checkout.SessionCreateParamsLineItem] = Field(default_factory=list)
    limits: JSONObject = Field(default_factory=dict)
    proration_behavior: StripeProrationBehavior | None = None
    free_trial: StripeFreeTrial | None = None

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
    seats: int | None = Field(default=None, ge=1)
    schedule_at_period_end: bool = False
    success_url: str
    cancel_url: str
    return_url: str | None = None
    disable_redirect: bool = False
    locale: StripeSubscriptionLocale | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ListSubscriptionsRequest(BaseModel):
    account_id: UUID | None = None
    active_only: bool = False


class CancelSubscriptionRequest(BaseModel):
    account_id: UUID | None = None
    subscription_id: UUID | None = None
    return_url: str
    disable_redirect: bool = False
    locale: BillingPortalLocale | None = None


class RestoreSubscriptionRequest(BaseModel):
    account_id: UUID | None = None
    subscription_id: UUID | None = None


class BillingPortalRequest(BaseModel):
    account_id: UUID | None = None
    return_url: str | None = None
    disable_redirect: bool = False
    locale: BillingPortalLocale | None = None


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
    trial_start: datetime | None = None
    trial_end: datetime | None = None
    seats: int | None = None
    cancel_at_period_end: bool
    cancel_at: datetime | None = None
    canceled_at: datetime | None = None
    ended_at: datetime | None = None
    billing_interval: StripeBillingInterval | None = None
    stripe_schedule_id: str | None = None
    price_id: str | None = None
    limits: JSONObject = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_subscription[T: StripeSubscriptionProtocol](
        cls,
        subscription: T,
        *,
        price_id: str | None = None,
        limits: JSONObject | None = None,
    ) -> Self:
        return cls.model_validate(
            {
                **cls.model_validate(subscription).model_dump(),
                "price_id": price_id,
                "limits": {} if limits is None else limits,
            },
        )


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
    checkout_session: CheckoutSession | None = None
    cancellation_details: Subscription.CancellationDetails | None = None


def account_type_label(account: StripeAccountProtocol) -> str:
    return account.account_type.value
