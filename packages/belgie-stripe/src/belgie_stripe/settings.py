from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.stripe import StripeAdapterProtocol, StripeCustomerProtocol, StripeSubscriptionProtocol
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from stripe import Event, StripeClient as StripeSDKClient
from stripe.params import CustomerCreateParams, checkout

from belgie_stripe.models import (
    CheckoutSessionContext,
    CustomerAuthorizationContext,
    CustomerCreateContext,
    StripePlan,
    SubscriptionEventContext,
)

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_stripe.plugin import StripePlugin


type MaybeAwaitable[T] = T | Awaitable[T]
type PlansResolver = Callable[[], list[StripePlan] | Awaitable[list[StripePlan]]]
type CustomerAuthorizationHook = Callable[
    [CustomerAuthorizationContext[StripeCustomerProtocol, IndividualProtocol[str], SessionProtocol]],
    MaybeAwaitable[bool],
]
type CustomerParamsHook = Callable[
    [CustomerCreateContext[StripeCustomerProtocol]],
    MaybeAwaitable[CustomerCreateParams | None],
]
type CustomerCreateHook = Callable[[CustomerCreateContext[StripeCustomerProtocol]], MaybeAwaitable[None]]
type CheckoutParamsHook[SubscriptionT: StripeSubscriptionProtocol] = Callable[
    [CheckoutSessionContext[SubscriptionT, StripeCustomerProtocol, IndividualProtocol[str], SessionProtocol]],
    MaybeAwaitable[checkout.SessionCreateParams | None],
]
type SubscriptionEventHook[SubscriptionT: StripeSubscriptionProtocol] = Callable[
    [SubscriptionEventContext[SubscriptionT, StripeCustomerProtocol]],
    MaybeAwaitable[None],
]
type RawEventHook = Callable[[Event], MaybeAwaitable[None]]


class StripeSubscription[
    SubscriptionT: StripeSubscriptionProtocol,
](BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_STRIPE_SUBSCRIPTION_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    adapter: StripeAdapterProtocol[SubscriptionT] = Field(exclude=True)
    plans: list[StripePlan] | PlansResolver
    require_email_verification: bool = False
    authorize_customer: CustomerAuthorizationHook | None = Field(default=None, exclude=True)
    get_checkout_session_params: CheckoutParamsHook[SubscriptionT] | None = Field(default=None, exclude=True)
    on_subscription_created: SubscriptionEventHook[SubscriptionT] | None = Field(default=None, exclude=True)
    on_subscription_updated: SubscriptionEventHook[SubscriptionT] | None = Field(default=None, exclude=True)
    on_subscription_canceled: SubscriptionEventHook[SubscriptionT] | None = Field(default=None, exclude=True)
    on_subscription_deleted: SubscriptionEventHook[SubscriptionT] | None = Field(default=None, exclude=True)

    @field_validator("adapter")
    @classmethod
    def validate_adapter(
        cls,
        value: StripeAdapterProtocol[SubscriptionT],
    ) -> StripeAdapterProtocol[SubscriptionT]:
        if not isinstance(value, StripeAdapterProtocol):
            msg = "adapter must implement StripeAdapterProtocol"
            raise TypeError(msg)
        return value


class Stripe[
    SubscriptionT: StripeSubscriptionProtocol,
](BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_STRIPE_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    stripe: StripeSDKClient = Field(exclude=True)
    stripe_webhook_secret: str
    create_customer_on_sign_up: bool = False
    get_customer_create_params: CustomerParamsHook | None = Field(default=None, exclude=True)
    on_customer_create: CustomerCreateHook | None = Field(default=None, exclude=True)
    on_event: RawEventHook | None = Field(default=None, exclude=True)
    subscription: StripeSubscription[SubscriptionT]

    def __call__(self, belgie_settings: BelgieSettings) -> StripePlugin[SubscriptionT]:
        from belgie_stripe.plugin import StripePlugin  # noqa: PLC0415

        return StripePlugin(belgie_settings, self)
