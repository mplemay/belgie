from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, overload
from uuid import UUID

import stripe
from belgie_proto.core.customer import CustomerType
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.stripe import (
    StripeBillingInterval,
    StripeCustomerProtocol,
    StripeSubscriptionProtocol,
    StripeSubscriptionStatus,
)
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from stripe import Event, StripeClient as StripeSDKClient, Subscription
from stripe._stripe_object import StripeObject
from stripe.checkout import Session as CheckoutSession
from stripe.params import CustomerCreateParams, PriceListParams, SubscriptionUpdateParams, billing_portal, checkout

from belgie_stripe.models import (
    BillingPortalRequest,
    CancelSubscriptionRequest,
    CheckoutSessionContext,
    CustomerAuthorizationContext,
    CustomerCreateContext,
    ListSubscriptionsRequest,
    RestoreSubscriptionRequest,
    StripeAction,
    StripePlan,
    StripeRedirectResponse,
    SubscriptionEventContext,
    SubscriptionView,
    UpgradeSubscriptionRequest,
)
from belgie_stripe.utils import (
    _is_awaitable,
    absolute_url,
    append_query_params,
    maybe_await,
    normalize_relative_or_same_origin_url,
    sign_success_token,
    unsign_success_token,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.core.session import SessionProtocol
    from belgie_proto.stripe import StripeAdapterProtocol

    from belgie_stripe._protocols import BelgieClientProtocol
    from belgie_stripe.settings import Stripe


type PlansResolver = Callable[[], list[StripePlan] | Awaitable[list[StripePlan]]]


SUCCESS_POLL_ATTEMPTS = 20
SUCCESS_POLL_INTERVAL_SECONDS = 0.05
SUCCESSFUL_SUBSCRIPTION_STATUSES = ("active", "past_due", "paused", "trialing", "unpaid")
TERMINAL_SUBSCRIPTION_STATUSES = ("canceled", "incomplete_expired")
NORMALIZED_SUBSCRIPTION_STATUSES: dict[str, StripeSubscriptionStatus] = {
    "active": "active",
    "canceled": "canceled",
    "incomplete": "incomplete",
    "incomplete_expired": "incomplete_expired",
    "past_due": "past_due",
    "paused": "paused",
    "trialing": "trialing",
    "unpaid": "unpaid",
}


class _HasID(Protocol):
    id: str


def _copy_customer_create_params(params: CustomerCreateParams | None) -> CustomerCreateParams:
    if params is None:
        return CustomerCreateParams()
    return CustomerCreateParams(params)


def _copy_checkout_session_params(params: checkout.SessionCreateParams | None) -> checkout.SessionCreateParams:
    if params is None:
        return checkout.SessionCreateParams()
    return checkout.SessionCreateParams(params)


def _copy_checkout_subscription_data(
    params: checkout.SessionCreateParamsSubscriptionData | None,
) -> checkout.SessionCreateParamsSubscriptionData:
    if params is None:
        return checkout.SessionCreateParamsSubscriptionData()
    return checkout.SessionCreateParamsSubscriptionData(params)


def _metadata_dict(metadata: StripeObject | dict[str, str] | None) -> dict[str, str]:
    if metadata is None:
        return {}
    if isinstance(metadata, StripeObject):
        raw_metadata = metadata.to_dict()
        return {key: value for key, value in raw_metadata.items() if isinstance(value, str)}
    return metadata


@overload
async def _resolve_plans(plans: list[StripePlan]) -> list[StripePlan]: ...


@overload
async def _resolve_plans(plans: PlansResolver) -> list[StripePlan]: ...


async def _resolve_plans(plans):
    if isinstance(plans, list):
        return plans
    resolved = plans()
    if _is_awaitable(resolved):
        return await resolved
    return resolved


@overload
async def _resolve_customer_create_params(params: CustomerCreateParams | None) -> CustomerCreateParams | None: ...


@overload
async def _resolve_customer_create_params(
    params: Awaitable[CustomerCreateParams | None],
) -> CustomerCreateParams | None: ...


async def _resolve_customer_create_params(params):
    if _is_awaitable(params):
        return await params
    return params


@overload
async def _resolve_checkout_session_params(
    params: checkout.SessionCreateParams | None,
) -> checkout.SessionCreateParams | None: ...


@overload
async def _resolve_checkout_session_params(
    params: Awaitable[checkout.SessionCreateParams | None],
) -> checkout.SessionCreateParams | None: ...


async def _resolve_checkout_session_params(params):
    if _is_awaitable(params):
        return await params
    return params


def _expandable_id(value: str | _HasID | None) -> str | None:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    return value.id


@dataclass(slots=True, kw_only=True)
class StripeClient[
    SubscriptionT: StripeSubscriptionProtocol,
]:
    client: BelgieClientProtocol[StripeCustomerProtocol, IndividualProtocol[str], SessionProtocol]
    belgie_settings: BelgieSettings
    settings: Stripe[SubscriptionT]
    current_individual: IndividualProtocol[str] | None = None
    current_session: SessionProtocol | None = None

    @property
    def subscription_adapter(self) -> StripeAdapterProtocol[SubscriptionT]:
        return self.settings.subscription.adapter

    @property
    def stripe(self) -> StripeSDKClient:
        return self.settings.stripe

    async def upgrade(
        self,
        *,
        data: UpgradeSubscriptionRequest,
    ) -> StripeRedirectResponse:
        individual, session = self._require_authenticated()
        if self.settings.subscription.require_email_verification and individual.email_verified_at is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email verification required")

        plan = await self._get_plan(data.plan)
        customer = await self._get_authorized_customer(
            action="upgrade-subscription",
            customer_id=data.customer_id,
        )

        success_url = self._validated_url(data.success_url)
        cancel_url = self._validated_url(data.cancel_url)
        return_url = self._validated_url(data.return_url) if data.return_url else success_url

        active_subscription = await self.subscription_adapter.get_active_subscription(
            self.client.db,
            customer_id=customer.id,
        )
        if active_subscription and active_subscription.plan.lower() == plan.name.lower():
            billing_interval = active_subscription.billing_interval
            if billing_interval is None or (
                (data.annual and billing_interval == "year") or (not data.annual and billing_interval != "year")
            ):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already subscribed to this plan")

        stripe_customer_id = active_subscription.stripe_customer_id if active_subscription else None
        if stripe_customer_id is None:
            stripe_customer_id = await self.ensure_customer(customer_id=customer.id, metadata=data.metadata)

        if active_subscription and active_subscription.stripe_subscription_id:
            portal_session = await self.stripe.v1.billing_portal.sessions.create_async(
                await self._build_upgrade_portal_params(
                    customer_id=stripe_customer_id,
                    return_url=absolute_url(self.belgie_settings.base_url, return_url),
                    subscription_id=active_subscription.stripe_subscription_id,
                    price_id=await self._resolve_price_id(plan=plan, annual=data.annual),
                ),
            )
            return StripeRedirectResponse(url=portal_session.url, redirect=not data.disable_redirect)

        pending_subscription = await self.subscription_adapter.get_incomplete_subscription(
            self.client.db,
            customer_id=customer.id,
        )
        if pending_subscription is None:
            subscription = await self.subscription_adapter.create_subscription(
                self.client.db,
                plan=plan.name.lower(),
                customer_id=customer.id,
                stripe_customer_id=stripe_customer_id,
            )
        else:
            subscription = await self.subscription_adapter.update_subscription(
                self.client.db,
                subscription_id=pending_subscription.id,
                plan=plan.name.lower(),
                stripe_customer_id=stripe_customer_id,
            )
            if subscription is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="failed to update subscription",
                )

        checkout_context = CheckoutSessionContext(
            customer=customer,
            plan=plan,
            subscription=subscription,
            individual=individual,
            session=session,
        )
        extra_params = (
            await _resolve_checkout_session_params(
                self.settings.subscription.get_checkout_session_params(checkout_context),
            )
            if self.settings.subscription.get_checkout_session_params
            else None
        )
        success_token = sign_success_token(
            secret=self.belgie_settings.secret,
            subscription_id=subscription.id,
            redirect_to=success_url,
        )
        internal_success_url = append_query_params(
            absolute_url(self.belgie_settings.base_url, "/auth/subscription/success"),
            token=success_token,
        )
        checkout_session = await self.stripe.v1.checkout.sessions.create_async(
            self._build_checkout_session_params(
                extra_params=extra_params,
                customer_id=stripe_customer_id,
                price_id=await self._resolve_price_id(plan=plan, annual=data.annual),
                redirect_urls=(
                    internal_success_url,
                    absolute_url(self.belgie_settings.base_url, cancel_url),
                ),
                metadata={
                    **data.metadata,
                    "customer_id": str(customer.id),
                    "customer_type": customer.customer_type,
                    "local_subscription_id": str(subscription.id),
                    "plan": plan.name.lower(),
                },
            ),
        )
        if checkout_session.url is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe checkout session did not return a url",
            )
        return StripeRedirectResponse(url=checkout_session.url, redirect=not data.disable_redirect)

    async def list_subscriptions(self, *, data: ListSubscriptionsRequest) -> list[SubscriptionView]:
        customer = await self._get_authorized_customer(
            action="list-subscription",
            customer_id=data.customer_id,
        )
        subscriptions = await self.subscription_adapter.list_subscriptions(
            self.client.db,
            customer_id=customer.id,
        )
        return [SubscriptionView.from_subscription(subscription) for subscription in subscriptions]

    async def cancel(
        self,
        *,
        data: CancelSubscriptionRequest,
    ) -> StripeRedirectResponse:
        customer = await self._get_authorized_customer(
            action="cancel-subscription",
            customer_id=data.customer_id,
        )
        stripe_customer_id = await self.ensure_customer(customer_id=customer.id, metadata={})
        portal_session = await self.stripe.v1.billing_portal.sessions.create_async(
            self._build_billing_portal_params(
                customer_id=stripe_customer_id,
                return_url=(
                    absolute_url(self.belgie_settings.base_url, self._validated_url(data.return_url))
                    if data.return_url
                    else absolute_url(self.belgie_settings.base_url, "/")
                ),
            ),
        )
        return StripeRedirectResponse(url=portal_session.url, redirect=not data.disable_redirect)

    async def restore(self, *, data: RestoreSubscriptionRequest) -> SubscriptionView:
        customer = await self._get_authorized_customer(
            action="restore-subscription",
            customer_id=data.customer_id,
        )
        subscription = await self.subscription_adapter.get_active_subscription(
            self.client.db,
            customer_id=customer.id,
        )
        if subscription is None or subscription.stripe_subscription_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
        if not subscription.cancel_at_period_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="subscription is not pending cancellation",
            )

        stripe_subscription = await self.stripe.v1.subscriptions.update_async(
            subscription.stripe_subscription_id,
            SubscriptionUpdateParams(cancel_at_period_end=False),
        )
        updated = await self._sync_subscription(
            stripe_subscription=stripe_subscription,
            event_type="customer.subscription.updated",
            existing_subscription=subscription,
        )
        return SubscriptionView.from_subscription(updated)

    async def create_billing_portal(
        self,
        *,
        data: BillingPortalRequest,
    ) -> StripeRedirectResponse:
        customer = await self._get_authorized_customer(
            action="billing-portal",
            customer_id=data.customer_id,
        )
        stripe_customer_id = await self.ensure_customer(customer_id=customer.id, metadata={})
        portal_session = await self.stripe.v1.billing_portal.sessions.create_async(
            self._build_billing_portal_params(
                customer_id=stripe_customer_id,
                return_url=(
                    absolute_url(self.belgie_settings.base_url, self._validated_url(data.return_url))
                    if data.return_url
                    else absolute_url(self.belgie_settings.base_url, "/")
                ),
            ),
        )
        return StripeRedirectResponse(url=portal_session.url, redirect=not data.disable_redirect)

    async def handle_webhook(self, *, request: Request) -> dict[str, bool]:
        payload = await request.body()
        signature = request.headers.get("stripe-signature")
        if signature is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing stripe-signature header")
        try:
            event = self.stripe.construct_event(payload, signature, self.settings.stripe_webhook_secret)
        except (stripe.error.SignatureVerificationError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid stripe webhook") from exc
        if self.settings.on_event is not None:
            await maybe_await(self.settings.on_event(event))

        if event.type == "checkout.session.completed":
            checkout_session = self._coerce_checkout_session_event(event)
            subscription_id = _expandable_id(checkout_session.subscription)
            metadata = _metadata_dict(checkout_session.metadata)
            local_subscription = await self._lookup_subscription_from_metadata(metadata)
            if subscription_id is not None:
                stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(subscription_id)
                await self._sync_subscription(
                    stripe_subscription=stripe_subscription,
                    event_type=event.type,
                    existing_subscription=local_subscription,
                )
        elif event.type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            stripe_subscription = self._coerce_subscription_event(event)
            existing_subscription = None
            if stripe_subscription.id:
                existing_subscription = await self.subscription_adapter.get_subscription_by_stripe_subscription_id(
                    self.client.db,
                    stripe_subscription_id=stripe_subscription.id,
                )
            await self._sync_subscription(
                stripe_subscription=stripe_subscription,
                event_type=event.type,
                existing_subscription=existing_subscription,
            )
        return {"received": True}

    async def subscription_success(self, *, token: str) -> RedirectResponse:
        try:
            subscription_id_str, redirect_to = unsign_success_token(
                secret=self.belgie_settings.secret,
                token=token,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        for _ in range(SUCCESS_POLL_ATTEMPTS):
            subscription = await self.subscription_adapter.get_subscription_by_id(
                self.client.db,
                UUID(subscription_id_str),
            )
            if subscription is None or subscription.status == "incomplete":
                await asyncio.sleep(SUCCESS_POLL_INTERVAL_SECONDS)
                continue
            if subscription.status in TERMINAL_SUBSCRIPTION_STATUSES:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="subscription could not be finalized")
            if (
                subscription.status in SUCCESSFUL_SUBSCRIPTION_STATUSES
                and subscription.stripe_subscription_id is not None
            ):
                return RedirectResponse(
                    url=absolute_url(self.belgie_settings.base_url, redirect_to),
                    status_code=status.HTTP_302_FOUND,
                )
            await asyncio.sleep(SUCCESS_POLL_INTERVAL_SECONDS)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="subscription is still being finalized")

    async def ensure_customer(
        self,
        *,
        customer_id: UUID,
        metadata: dict[str, str],
    ) -> str:
        customer = await self._get_customer_by_id(customer_id)
        if customer.stripe_customer_id:
            return customer.stripe_customer_id

        context = CustomerCreateContext(
            customer=customer,
            stripe_customer_id="",
            metadata=metadata,
        )
        extra_params = (
            await _resolve_customer_create_params(self.settings.get_customer_create_params(context))
            if self.settings.get_customer_create_params
            else None
        )
        payload = _copy_customer_create_params(extra_params)
        self._apply_customer_identity(payload=payload, customer=customer)
        payload["metadata"] = {
            **(payload.get("metadata") or {}),
            **metadata,
            "customer_id": str(customer.id),
            "customer_type": customer.customer_type,
        }
        stripe_customer = await self.stripe.v1.customers.create_async(payload)
        stripe_customer_id = stripe_customer.id
        await self.client.adapter.update_customer(
            self.client.db,
            customer.id,
            stripe_customer_id=stripe_customer_id,
        )
        if self.settings.on_customer_create is not None:
            await maybe_await(
                self.settings.on_customer_create(
                    CustomerCreateContext(
                        customer=customer,
                        stripe_customer_id=stripe_customer_id,
                        metadata=metadata,
                    ),
                ),
            )
        return stripe_customer_id

    async def _get_authorized_customer(
        self,
        *,
        action: StripeAction,
        customer_id: UUID | None,
    ) -> StripeCustomerProtocol:
        customer = await self._get_customer_by_id(self._resolve_customer_id(customer_id))
        await self._authorize_customer(action=action, customer=customer)
        return customer

    async def _get_customer_by_id(self, customer_id: UUID) -> StripeCustomerProtocol:
        customer = await self.client.adapter.get_customer_by_id(self.client.db, customer_id)
        if customer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="customer not found")
        if not isinstance(customer, StripeCustomerProtocol):
            msg = "customer model must expose stripe_customer_id"
            raise TypeError(msg)
        return customer

    async def _authorize_customer(
        self,
        *,
        action: StripeAction,
        customer: StripeCustomerProtocol,
    ) -> None:
        individual, session = self._require_authenticated()
        if customer.id == individual.id:
            return
        if self.settings.subscription.authorize_customer is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="customer billing requires authorize_customer",
            )
        allowed = await maybe_await(
            self.settings.subscription.authorize_customer(
                CustomerAuthorizationContext(
                    action=action,
                    customer=customer,
                    individual=individual,
                    session=session,
                ),
            ),
        )
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not authorized")

    async def _get_plan(self, name: str) -> StripePlan:
        for plan in await self._get_plans():
            if plan.name.lower() == name.lower():
                return plan
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription plan not found")

    async def _get_plans(self) -> list[StripePlan]:
        return await _resolve_plans(self.settings.subscription.plans)

    async def _resolve_price_id(self, *, plan: StripePlan, annual: bool) -> str:
        if annual:
            if plan.annual_price_id:
                return plan.annual_price_id
            if plan.annual_lookup_key:
                return await self._resolve_lookup_key(plan.annual_lookup_key)
            msg = "plan is missing an annual stripe price"
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        if plan.price_id:
            return plan.price_id
        if plan.lookup_key:
            return await self._resolve_lookup_key(plan.lookup_key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="plan is missing a stripe price")

    async def _resolve_lookup_key(self, lookup_key: str) -> str:
        price_list = await self.stripe.v1.prices.list_async(
            PriceListParams(lookup_keys=[lookup_key], active=True, limit=1),
        )
        for price in price_list.data:
            return price.id
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="stripe price not found")

    def _resolve_customer_id(self, customer_id: UUID | None) -> UUID:
        individual, _session = self._require_authenticated()
        return customer_id or individual.id

    def _apply_customer_identity(
        self,
        *,
        payload: CustomerCreateParams,
        customer: StripeCustomerProtocol,
    ) -> None:
        if customer.customer_type == CustomerType.INDIVIDUAL:
            if not isinstance(customer, IndividualProtocol):
                msg = "individual customer must expose email"
                raise TypeError(msg)
            payload["email"] = customer.email
            if customer.name is not None:
                payload["name"] = customer.name
            return
        if customer.name is not None:
            payload["name"] = customer.name

    def _validated_url(self, url: str) -> str:
        if (normalized := normalize_relative_or_same_origin_url(url, base_url=self.belgie_settings.base_url)) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="url must be relative or same-origin")
        return normalized

    def _coerce_stripe_uuid(self, value: str, *, field_name: str) -> UUID:
        try:
            return UUID(value)
        except ValueError as exc:
            detail = f"stripe metadata {field_name} must be a valid UUID"
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc

    def _build_billing_portal_params(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> billing_portal.SessionCreateParams:
        return billing_portal.SessionCreateParams(
            customer=customer_id,
            return_url=return_url,
        )

    async def _build_upgrade_portal_params(
        self,
        *,
        customer_id: str,
        return_url: str,
        subscription_id: str,
        price_id: str,
    ) -> billing_portal.SessionCreateParams:
        stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(subscription_id)
        if not stripe_subscription.items.data:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe subscription missing items",
            )

        return billing_portal.SessionCreateParams(
            customer=customer_id,
            return_url=return_url,
            flow_data=billing_portal.SessionCreateParamsFlowData(
                type="subscription_update_confirm",
                after_completion=billing_portal.SessionCreateParamsFlowDataAfterCompletion(
                    type="redirect",
                    redirect=billing_portal.SessionCreateParamsFlowDataAfterCompletionRedirect(
                        return_url=return_url,
                    ),
                ),
                subscription_update_confirm=billing_portal.SessionCreateParamsFlowDataSubscriptionUpdateConfirm(
                    subscription=subscription_id,
                    items=[
                        billing_portal.SessionCreateParamsFlowDataSubscriptionUpdateConfirmItem(
                            id=stripe_subscription.items.data[0].id,
                            price=price_id,
                        ),
                    ],
                ),
            ),
        )

    def _build_checkout_session_params(
        self,
        *,
        extra_params: checkout.SessionCreateParams | None,
        customer_id: str,
        price_id: str,
        redirect_urls: tuple[str, str],
        metadata: dict[str, str],
    ) -> checkout.SessionCreateParams:
        success_url, cancel_url = redirect_urls
        payload = _copy_checkout_session_params(extra_params)
        payload["mode"] = "subscription"
        payload["customer"] = customer_id
        payload["line_items"] = [
            checkout.SessionCreateParamsLineItem(price=price_id, quantity=1),
        ]
        payload["success_url"] = success_url
        payload["cancel_url"] = cancel_url
        payload["metadata"] = {
            **(payload.get("metadata") or {}),
            **metadata,
        }

        subscription_data = _copy_checkout_subscription_data(payload.get("subscription_data"))
        subscription_data["metadata"] = {
            **(subscription_data.get("metadata") or {}),
            **metadata,
        }
        payload["subscription_data"] = subscription_data
        return payload

    def _coerce_checkout_session_event(self, event: Event) -> CheckoutSession:
        return CheckoutSession.construct_from(event.data.object, key=None)

    def _coerce_subscription_event(self, event: Event) -> Subscription:
        return Subscription.construct_from(event.data.object, key=None)

    async def _lookup_subscription_from_metadata(self, metadata: dict[str, str]) -> SubscriptionT | None:
        if (metadata_subscription_id := metadata.get("local_subscription_id")) is None:
            return None
        return await self.subscription_adapter.get_subscription_by_id(
            self.client.db,
            self._coerce_stripe_uuid(metadata_subscription_id, field_name="local_subscription_id"),
        )

    async def _sync_subscription(
        self,
        *,
        stripe_subscription: Subscription,
        event_type: str,
        existing_subscription: SubscriptionT | None,
    ) -> SubscriptionT:
        metadata = _metadata_dict(stripe_subscription.metadata)
        subscription = existing_subscription or await self._lookup_subscription_from_metadata(metadata)

        customer_id_raw = metadata.get("customer_id")
        if customer_id_raw is not None:
            customer_id = self._coerce_stripe_uuid(customer_id_raw, field_name="customer_id")
        elif subscription is not None:
            customer_id = subscription.customer_id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="stripe subscription metadata missing customer_id",
            )

        customer = await self._get_customer_by_id(customer_id)
        plan_name = metadata.get("plan")
        plan = await self._match_plan(plan_name=plan_name, stripe_subscription=stripe_subscription)
        recurring = self._extract_primary_recurring(stripe_subscription)
        stripe_customer_id = _expandable_id(stripe_subscription.customer)
        period_start = self._timestamp_to_datetime(getattr(stripe_subscription, "current_period_start", None))
        period_end = self._timestamp_to_datetime(getattr(stripe_subscription, "current_period_end", None))
        cancel_at = self._timestamp_to_datetime(stripe_subscription.cancel_at)
        canceled_at = self._timestamp_to_datetime(stripe_subscription.canceled_at)
        ended_at = self._timestamp_to_datetime(stripe_subscription.ended_at)
        normalized_status = self._normalize_status(stripe_subscription.status)

        if subscription is None:
            subscription = await self.subscription_adapter.create_subscription(
                self.client.db,
                plan=plan.name.lower(),
                customer_id=customer.id,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription.id,
                status=normalized_status,
                period_start=period_start,
                period_end=period_end,
                cancel_at_period_end=stripe_subscription.cancel_at_period_end,
                cancel_at=cancel_at,
                canceled_at=canceled_at,
                ended_at=ended_at,
                billing_interval=recurring,
            )
        else:
            updated = await self.subscription_adapter.update_subscription(
                self.client.db,
                subscription_id=subscription.id,
                plan=plan.name.lower(),
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription.id,
                status=normalized_status,
                period_start=period_start,
                period_end=period_end,
                cancel_at_period_end=stripe_subscription.cancel_at_period_end,
                cancel_at=cancel_at,
                canceled_at=canceled_at,
                ended_at=ended_at,
                billing_interval=recurring,
            )
            if updated is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="failed to update subscription",
                )
            subscription = updated

        hook_context = SubscriptionEventContext(
            event_type=event_type,
            plan=plan,
            raw_event=stripe_subscription,
            subscription=subscription,
            customer=customer,
        )
        if (
            event_type == "customer.subscription.created"
            and self.settings.subscription.on_subscription_created is not None
        ):
            await maybe_await(self.settings.subscription.on_subscription_created(hook_context))
        elif (
            event_type == "customer.subscription.updated"
            and self.settings.subscription.on_subscription_updated is not None
        ):
            await maybe_await(self.settings.subscription.on_subscription_updated(hook_context))
        elif event_type == "customer.subscription.deleted":
            if self.settings.subscription.on_subscription_deleted is not None:
                await maybe_await(self.settings.subscription.on_subscription_deleted(hook_context))
            if self.settings.subscription.on_subscription_canceled is not None:
                await maybe_await(self.settings.subscription.on_subscription_canceled(hook_context))
        return subscription

    async def _match_plan(self, *, plan_name: str | None, stripe_subscription: Subscription) -> StripePlan:
        if plan_name is not None:
            return await self._get_plan(plan_name)
        plans = await self._get_plans()
        for item in stripe_subscription.items.data:
            price = item.price
            for plan in plans:
                if price.id in {plan.price_id, plan.annual_price_id}:
                    return plan
                if price.lookup_key in {plan.lookup_key, plan.annual_lookup_key}:
                    return plan
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription plan not found")

    def _extract_primary_recurring(self, stripe_subscription: Subscription) -> StripeBillingInterval | None:
        for item in stripe_subscription.items.data:
            if (recurring := item.price.recurring) is not None:
                return self._normalize_billing_interval(recurring.interval)
        return None

    def _normalize_status(self, status_value: str) -> StripeSubscriptionStatus:
        if (normalized_status := NORMALIZED_SUBSCRIPTION_STATUSES.get(status_value)) is not None:
            return normalized_status
        msg = f"unsupported stripe subscription status: {status_value}"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    def _normalize_billing_interval(self, interval: str) -> StripeBillingInterval:
        match interval:
            case "day":
                return "day"
            case "month":
                return "month"
            case "week":
                return "week"
            case "year":
                return "year"
            case _:
                msg = f"unsupported stripe billing interval: {interval}"
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    def _timestamp_to_datetime(self, value: object) -> datetime | None:
        if not isinstance(value, (int, float)):
            return None
        return datetime.fromtimestamp(value, UTC)

    def _require_authenticated(self) -> tuple[IndividualProtocol[str], SessionProtocol]:
        if self.current_individual is None or self.current_session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
        return self.current_individual, self.current_session
