from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from belgie_proto.core.session import SessionProtocol
from belgie_proto.stripe import (
    StripeAdapterProtocol,
    StripeOrganizationProtocol,
    StripeSubscriptionProtocol,
    StripeUserProtocol,
)
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from stripe import StripeClient as StripeSDKClient  # noqa: TC002

from belgie_stripe.models import (
    CheckoutSessionContext,
    CustomerCreateContext,
    JSONScalar,
    ReferenceAuthorizationContext,
    StripePlan,
    SubscriptionEventContext,
)

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_stripe.plugin import StripePlugin


type JSONParams = dict[str, JSONScalar | dict[str, JSONScalar]]
type MaybeAwaitable[T] = T | Awaitable[T]
type PlansResolver = Callable[[], list[StripePlan] | Awaitable[list[StripePlan]]]
type ReferenceAuthorizationHook = Callable[
    [ReferenceAuthorizationContext[StripeUserProtocol[str], SessionProtocol]],
    MaybeAwaitable[bool],
]
type UserCustomerParamsHook = Callable[
    [CustomerCreateContext[StripeUserProtocol[str]]],
    MaybeAwaitable[JSONParams | None],
]
type OrganizationCustomerParamsHook = Callable[
    [CustomerCreateContext[StripeOrganizationProtocol]],
    MaybeAwaitable[JSONParams | None],
]
type UserCustomerCreateHook = Callable[[CustomerCreateContext[StripeUserProtocol[str]]], MaybeAwaitable[None]]
type OrganizationCustomerCreateHook = Callable[
    [CustomerCreateContext[StripeOrganizationProtocol]],
    MaybeAwaitable[None],
]
type CheckoutParamsHook[SubscriptionT: StripeSubscriptionProtocol] = Callable[
    [CheckoutSessionContext[SubscriptionT, StripeUserProtocol[str], SessionProtocol]],
    MaybeAwaitable[JSONParams | None],
]
type SubscriptionEventHook[SubscriptionT: StripeSubscriptionProtocol] = Callable[
    [SubscriptionEventContext[SubscriptionT]],
    MaybeAwaitable[None],
]
type RawEventHook = Callable[[object], MaybeAwaitable[None]]


class StripeOrganization(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_STRIPE_ORGANIZATION_",
        env_file=".env",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    enabled: bool = False
    get_customer_create_params: OrganizationCustomerParamsHook | None = Field(default=None, exclude=True)
    on_customer_create: OrganizationCustomerCreateHook | None = Field(default=None, exclude=True)


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
    authorize_reference: ReferenceAuthorizationHook | None = Field(default=None, exclude=True)
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
    get_customer_create_params: UserCustomerParamsHook | None = Field(default=None, exclude=True)
    on_customer_create: UserCustomerCreateHook | None = Field(default=None, exclude=True)
    on_event: RawEventHook | None = Field(default=None, exclude=True)
    subscription: StripeSubscription[SubscriptionT]
    organization: StripeOrganization | None = None

    def __call__(self, belgie_settings: BelgieSettings) -> StripePlugin[SubscriptionT]:
        from belgie_stripe.plugin import StripePlugin  # noqa: PLC0415

        return StripePlugin(belgie_settings, self)
