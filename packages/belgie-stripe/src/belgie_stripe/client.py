from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, overload
from uuid import UUID

import stripe
from belgie_proto.core.account import AccountType
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.stripe import (
    StripeAccountProtocol,
    StripeAdapterProtocol,
    StripeBillingInterval,
    StripeSubscriptionProtocol,
    StripeSubscriptionStatus,
)
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from stripe import Event, StripeClient as StripeSDKClient, Subscription
from stripe._stripe_object import StripeObject
from stripe.checkout import Session as CheckoutSession
from stripe.params import (
    CustomerCreateParams,
    CustomerListParams,
    CustomerSearchParams,
    CustomerUpdateParams,
    PriceListParams,
    SubscriptionScheduleCreateParams,
    SubscriptionScheduleReleaseParams,
    SubscriptionScheduleUpdateParams,
    SubscriptionUpdateParams,
    billing_portal,
    checkout,
)
from stripe.params._subscription_schedule_update_params import (
    SubscriptionScheduleUpdateParamsPhase,
    SubscriptionScheduleUpdateParamsPhaseItem,
)
from stripe.params._subscription_update_params import SubscriptionUpdateParamsItem

from belgie_stripe.metadata import (
    customer_metadata,
    parse_customer_metadata,
    parse_schedule_metadata,
    parse_subscription_metadata,
    schedule_metadata,
    subscription_metadata,
)
from belgie_stripe.models import (
    AccountAuthorizationContext,
    AccountCreateContext,
    BillingPortalLocale,
    BillingPortalRequest,
    CancelSubscriptionRequest,
    CheckoutSessionContext,
    ListSubscriptionsRequest,
    RestoreSubscriptionRequest,
    StripeAction,
    StripePlan,
    StripeProrationBehavior,
    StripeRedirectResponse,
    StripeSubscriptionLocale,
    SubscriptionEventContext,
    SubscriptionView,
    UpgradeSubscriptionRequest,
)
from belgie_stripe.utils import (
    _is_awaitable,
    absolute_url,
    append_query_params,
    escape_stripe_search_value,
    maybe_await,
    normalize_relative_or_same_origin_url,
    sign_success_token,
    unsign_success_token,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.core.session import SessionProtocol
    from belgie_proto.organization import OrganizationAdapterProtocol

    from belgie_stripe._protocols import BelgieClientProtocol
    from belgie_stripe.settings import Stripe


type PlansResolver = Callable[[], list[StripePlan] | Awaitable[list[StripePlan]]]


logger = logging.getLogger(__name__)


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


class _SubscriptionRecurring(Protocol):
    interval: str
    usage_type: str | None


class _SubscriptionPrice(Protocol):
    id: str
    lookup_key: str | None
    recurring: _SubscriptionRecurring | None


class _SubscriptionItem(Protocol):
    id: str
    price: _SubscriptionPrice
    quantity: int | None


@dataclass(slots=True, kw_only=True, frozen=True)
class DesiredSubscriptionItem:
    price_id: str
    quantity: int | None


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
    client: BelgieClientProtocol[StripeAccountProtocol, IndividualProtocol[str], SessionProtocol]
    belgie_settings: BelgieSettings
    settings: Stripe[SubscriptionT]
    current_individual: IndividualProtocol[str] | None = None
    current_session: SessionProtocol | None = None
    organization_adapter: OrganizationAdapterProtocol | None = None

    @property
    def subscription_adapter(self) -> StripeAdapterProtocol[SubscriptionT]:
        return self.settings.subscription.adapter

    @property
    def stripe(self) -> StripeSDKClient:
        return self.settings.stripe

    async def upgrade(  # noqa: C901
        self,
        *,
        data: UpgradeSubscriptionRequest,
    ) -> StripeRedirectResponse:
        individual, session = self._require_authenticated()
        if self.settings.subscription.require_email_verification and individual.email_verified_at is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email verification required")

        plan = await self._get_plan(data.plan)
        account = await self._get_authorized_account(
            action="upgrade-subscription",
            account_id=data.account_id,
        )

        success_url = self._validated_url(data.success_url)
        cancel_url = self._validated_url(data.cancel_url)
        return_url = self._validated_url(data.return_url) if data.return_url else success_url

        active_subscription = await self.subscription_adapter.get_active_subscription(
            self.client.db,
            account_id=account.id,
        )
        base_price_id = await self._resolve_price_id(plan=plan, annual=data.annual)
        desired_items = await self._build_desired_subscription_items(
            account=account,
            plan=plan,
            base_price_id=base_price_id,
            seats=data.seats,
        )

        if (
            active_subscription is not None
            and active_subscription.plan.lower() == plan.name.lower()
            and active_subscription.stripe_schedule_id is None
            and data.seats is None
            and plan.seat_price_id is None
            and not plan.line_items
            and (
                (data.annual and active_subscription.billing_interval == "year")
                or (not data.annual and active_subscription.billing_interval != "year")
            )
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already subscribed to this plan")

        stripe_customer_id = active_subscription.stripe_customer_id if active_subscription else None
        if stripe_customer_id is None:
            stripe_customer_id = await self.ensure_account(account_id=account.id, metadata=data.metadata)

        if active_subscription and active_subscription.stripe_subscription_id is not None:
            stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(
                active_subscription.stripe_subscription_id,
            )
            current_items = list(stripe_subscription.items.data)
            subscription_matches = self._subscription_matches_desired_items(
                current_items=current_items,
                desired_items=desired_items,
            )
            has_pending_schedule = active_subscription.stripe_schedule_id is not None
            if subscription_matches and not has_pending_schedule:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already subscribed to this plan")
            if has_pending_schedule and subscription_matches:
                await self._release_plugin_schedule(active_subscription)
                return StripeRedirectResponse(
                    url=absolute_url(self.belgie_settings.base_url, return_url),
                    redirect=not data.disable_redirect,
                )

            active_subscription = await self._release_plugin_schedule_if_present(active_subscription)
            if data.schedule_at_period_end:
                await self._schedule_subscription_change(
                    account=account,
                    subscription=active_subscription,
                    stripe_subscription=stripe_subscription,
                    plan=plan,
                    desired_items=desired_items,
                )
                return StripeRedirectResponse(
                    url=absolute_url(self.belgie_settings.base_url, return_url),
                    redirect=not data.disable_redirect,
                )

            if len(current_items) == 1 and len(desired_items) == 1:
                portal_session = await self.stripe.v1.billing_portal.sessions.create_async(
                    self._build_upgrade_portal_params(
                        customer_id=stripe_customer_id,
                        return_url=absolute_url(self.belgie_settings.base_url, return_url),
                        stripe_subscription=stripe_subscription,
                        desired_item=desired_items[0],
                        locale=data.locale,
                    ),
                )
                return StripeRedirectResponse(url=portal_session.url, redirect=not data.disable_redirect)

            updated_subscription = await self.stripe.v1.subscriptions.update_async(
                active_subscription.stripe_subscription_id,
                SubscriptionUpdateParams(
                    items=self._build_subscription_update_items(
                        current_items=current_items,
                        desired_items=desired_items,
                    ),
                    metadata=subscription_metadata(
                        account=account,
                        subscription_id=active_subscription.id,
                        plan=plan.name.lower(),
                        metadata=data.metadata,
                    ),
                    **({} if plan.proration_behavior is None else {"proration_behavior": plan.proration_behavior}),
                ),
            )
            await self._sync_subscription(
                stripe_subscription=updated_subscription,
                event_type="customer.subscription.updated",
                existing_subscription=active_subscription,
            )
            return StripeRedirectResponse(
                url=absolute_url(self.belgie_settings.base_url, return_url),
                redirect=not data.disable_redirect,
            )

        pending_subscription = await self.subscription_adapter.get_incomplete_subscription(
            self.client.db,
            account_id=account.id,
        )
        if pending_subscription is None:
            subscription = await self.subscription_adapter.create_subscription(
                self.client.db,
                plan=plan.name.lower(),
                account_id=account.id,
                stripe_customer_id=stripe_customer_id,
            )
        else:
            subscription = await self.subscription_adapter.update_subscription(
                self.client.db,
                subscription_id=pending_subscription.id,
                plan=plan.name.lower(),
                stripe_customer_id=stripe_customer_id,
                stripe_schedule_id=None,
            )
            if subscription is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="failed to update subscription",
                )

        checkout_context = CheckoutSessionContext(
            account=account,
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
            checkout_session_id="{CHECKOUT_SESSION_ID}",
        )
        checkout_session = await self.stripe.v1.checkout.sessions.create_async(
            await self._build_checkout_session_params(
                extra_params=extra_params,
                customer_id=stripe_customer_id,
                line_items=await self._build_checkout_line_items(desired_items),
                redirect_urls=(
                    internal_success_url,
                    absolute_url(self.belgie_settings.base_url, cancel_url),
                ),
                metadata=subscription_metadata(
                    account=account,
                    subscription_id=subscription.id,
                    plan=plan.name.lower(),
                    metadata=data.metadata,
                ),
                locale=data.locale,
                trial_days=await self._trial_days_for_checkout(account_id=account.id, plan=plan),
                proration_behavior=plan.proration_behavior,
            ),
        )
        if checkout_session.url is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe checkout session did not return a url",
            )
        return StripeRedirectResponse(url=checkout_session.url, redirect=not data.disable_redirect)

    async def list_subscriptions(self, *, data: ListSubscriptionsRequest) -> list[SubscriptionView]:
        account = await self._get_authorized_account(
            action="list-subscription",
            account_id=data.account_id,
        )
        subscriptions = await self.subscription_adapter.list_subscriptions(
            self.client.db,
            account_id=account.id,
            active_only=data.active_only,
        )
        views: list[SubscriptionView] = []
        for subscription in subscriptions:
            plan = await self._find_plan(subscription.plan)
            price_id = await self._resolve_view_price_id(plan=plan, subscription=subscription)
            views.append(
                SubscriptionView.from_subscription(
                    subscription,
                    price_id=price_id,
                    limits={} if plan is None else plan.limits,
                ),
            )
        return views

    async def cancel(
        self,
        *,
        data: CancelSubscriptionRequest,
    ) -> StripeRedirectResponse:
        account, subscription = await self._resolve_target_subscription(
            action="cancel-subscription",
            account_id=data.account_id,
            subscription_id=data.subscription_id,
        )
        if subscription.stripe_subscription_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")

        stripe_customer_id = subscription.stripe_customer_id or await self.ensure_account(
            account_id=account.id,
            metadata={},
        )
        try:
            portal_session = await self.stripe.v1.billing_portal.sessions.create_async(
                self._build_cancel_portal_params(
                    customer_id=stripe_customer_id,
                    return_url=absolute_url(
                        self.belgie_settings.base_url,
                        self._validated_url(data.return_url),
                    ),
                    subscription_id=subscription.stripe_subscription_id,
                    locale=data.locale,
                ),
            )
        except Exception as exc:
            if self._should_sync_pending_cancellation(exc):
                try:
                    await self._sync_pending_cancellation_from_stripe(subscription=subscription)
                except Exception:
                    logger.exception(
                        "failed to sync pending stripe cancellation state",
                        extra={"subscription_id": str(subscription.id)},
                    )
            raise
        return StripeRedirectResponse(url=portal_session.url, redirect=not data.disable_redirect)

    async def restore(self, *, data: RestoreSubscriptionRequest) -> SubscriptionView:
        _account, subscription = await self._resolve_target_subscription(
            action="restore-subscription",
            account_id=data.account_id,
            subscription_id=data.subscription_id,
        )

        if subscription.stripe_schedule_id is not None:
            updated = await self._release_plugin_schedule(subscription)
            return SubscriptionView.from_subscription(
                updated,
                price_id=await self._resolve_view_price_id(
                    plan=await self._find_plan(updated.plan),
                    subscription=updated,
                ),
                limits={},
            )

        if subscription.stripe_subscription_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")

        stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(subscription.stripe_subscription_id)
        if stripe_subscription.cancel_at_period_end:
            updated_subscription = await self.stripe.v1.subscriptions.update_async(
                subscription.stripe_subscription_id,
                SubscriptionUpdateParams(cancel_at_period_end=False),
            )
        elif isinstance(stripe_subscription.cancel_at, int):
            updated_subscription = await self.stripe.v1.subscriptions.update_async(
                subscription.stripe_subscription_id,
                SubscriptionUpdateParams(cancel_at=""),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="subscription is not pending cancellation",
            )

        updated = await self._sync_subscription(
            stripe_subscription=updated_subscription,
            event_type="customer.subscription.updated",
            existing_subscription=subscription,
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
        return SubscriptionView.from_subscription(
            updated,
            price_id=await self._resolve_view_price_id(
                plan=await self._find_plan(updated.plan),
                subscription=updated,
            ),
            limits={},
        )

    async def create_billing_portal(
        self,
        *,
        data: BillingPortalRequest,
    ) -> StripeRedirectResponse:
        account = await self._get_authorized_account(
            action="billing-portal",
            account_id=data.account_id,
        )
        stripe_customer_id = await self.ensure_account(account_id=account.id, metadata={})
        portal_session = await self.stripe.v1.billing_portal.sessions.create_async(
            self._build_billing_portal_params(
                customer_id=stripe_customer_id,
                return_url=(
                    absolute_url(self.belgie_settings.base_url, self._validated_url(data.return_url))
                    if data.return_url
                    else absolute_url(self.belgie_settings.base_url, "/")
                ),
                locale=data.locale,
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
            if local_subscription is None and subscription_id is not None:
                local_subscription = await self.subscription_adapter.get_subscription_by_stripe_subscription_id(
                    self.client.db,
                    stripe_subscription_id=subscription_id,
                )
            if subscription_id is not None:
                stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(subscription_id)
                await self._sync_subscription(
                    stripe_subscription=stripe_subscription,
                    event_type=event.type,
                    existing_subscription=local_subscription,
                    checkout_session=checkout_session,
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

    async def subscription_success(
        self,
        *,
        token: str,
        checkout_session_id: str | None = None,
    ) -> RedirectResponse:
        try:
            subscription_id_str, redirect_to = unsign_success_token(
                secret=self.belgie_settings.secret,
                token=token,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        if checkout_session_id is not None:
            await self._sync_checkout_session(checkout_session_id)

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

    async def ensure_account(
        self,
        *,
        account_id: UUID,
        metadata: dict[str, str],
    ) -> str:
        account = await self._get_account_by_id(account_id)
        if account.stripe_customer_id:
            return account.stripe_customer_id

        if (existing_customer := await self._find_existing_customer(account)) is not None:
            await self.client.adapter.update_account(
                self.client.db,
                account.id,
                stripe_customer_id=existing_customer.id,
            )
            return existing_customer.id

        context = AccountCreateContext(
            account=account,
            stripe_customer_id="",
            metadata=metadata,
        )
        extra_params = (
            await _resolve_customer_create_params(self.settings.get_account_create_params(context))
            if self.settings.get_account_create_params
            else None
        )
        payload = _copy_customer_create_params(extra_params)
        self._apply_account_identity(payload=payload, account=account)
        payload["metadata"] = customer_metadata(
            account=account,
            metadata={
                **(payload.get("metadata") or {}),
                **metadata,
            },
        )
        stripe_customer = await self.stripe.v1.customers.create_async(payload)
        stripe_customer_id = stripe_customer.id
        await self.client.adapter.update_account(
            self.client.db,
            account.id,
            stripe_customer_id=stripe_customer_id,
        )
        if self.settings.on_account_create is not None:
            await maybe_await(
                self.settings.on_account_create(
                    AccountCreateContext(
                        account=account,
                        stripe_customer_id=stripe_customer_id,
                        metadata=metadata,
                    ),
                ),
            )
        return stripe_customer_id

    async def sync_individual_email(
        self,
        *,
        previous_individual: IndividualProtocol[str],
        individual: IndividualProtocol[str],
    ) -> None:
        if previous_individual.email == individual.email:
            return
        if not isinstance(individual, StripeAccountProtocol) or individual.stripe_customer_id is None:
            return

        stripe_customer = await self.stripe.v1.customers.retrieve_async(individual.stripe_customer_id)
        if getattr(stripe_customer, "deleted", False):
            return
        if getattr(stripe_customer, "email", None) == individual.email:
            return

        await self.stripe.v1.customers.update_async(
            individual.stripe_customer_id,
            CustomerUpdateParams(email=individual.email),
        )

    async def sync_organization_name(self, *, organization_id: UUID) -> None:
        organization = await self._get_account_by_id(organization_id)
        if organization.account_type != AccountType.ORGANIZATION or organization.stripe_customer_id is None:
            return
        await self.stripe.v1.customers.update_async(
            organization.stripe_customer_id,
            CustomerUpdateParams(name=organization.name),
        )

    async def ensure_organization_can_delete(self, *, organization_id: UUID) -> None:
        organization = await self._get_account_by_id(organization_id)
        if organization.account_type != AccountType.ORGANIZATION:
            return
        if (
            await self.subscription_adapter.get_active_subscription(
                self.client.db,
                account_id=organization.id,
            )
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="organization has an active subscription",
            )

    async def sync_organization_seats(self, *, organization_id: UUID) -> None:
        if self.organization_adapter is None:
            return
        organization = await self._get_account_by_id(organization_id)
        if organization.account_type != AccountType.ORGANIZATION:
            return
        subscription = await self.subscription_adapter.get_active_subscription(
            self.client.db,
            account_id=organization.id,
        )
        if subscription is None or subscription.stripe_subscription_id is None:
            return
        plan = await self._find_plan(subscription.plan)
        if plan is None or plan.seat_price_id is None:
            return

        stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(subscription.stripe_subscription_id)
        desired_items = await self._build_desired_subscription_items(
            account=organization,
            plan=plan,
            base_price_id=await self._resolve_price_id(
                plan=plan,
                annual=self._is_annual_subscription(
                    subscription=subscription,
                    stripe_subscription=stripe_subscription,
                    plan=plan,
                ),
            ),
            seats=None,
        )
        updated_subscription = await self.stripe.v1.subscriptions.update_async(
            subscription.stripe_subscription_id,
            SubscriptionUpdateParams(
                items=self._build_subscription_update_items(
                    current_items=list(stripe_subscription.items.data),
                    desired_items=desired_items,
                ),
                metadata=subscription_metadata(
                    account=organization,
                    subscription_id=subscription.id,
                    plan=subscription.plan,
                    metadata={},
                ),
                **({} if plan.proration_behavior is None else {"proration_behavior": plan.proration_behavior}),
            ),
        )
        await self._sync_subscription(
            stripe_subscription=updated_subscription,
            event_type="customer.subscription.updated",
            existing_subscription=subscription,
        )

    async def _get_authorized_account(
        self,
        *,
        action: StripeAction,
        account_id: UUID | None,
    ) -> StripeAccountProtocol:
        account = await self._get_account_by_id(self._resolve_account_id(account_id))
        await self._authorize_account(action=action, account=account)
        return account

    async def _get_account_by_id(self, account_id: UUID) -> StripeAccountProtocol:
        account = await self.client.adapter.get_account_by_id(self.client.db, account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
        if not isinstance(account, StripeAccountProtocol):
            msg = "account model must expose stripe_customer_id"
            raise TypeError(msg)
        return account

    async def _authorize_account(
        self,
        *,
        action: StripeAction,
        account: StripeAccountProtocol,
    ) -> None:
        individual, session = self._require_authenticated()
        if account.id == individual.id:
            return
        if self.settings.subscription.authorize_account is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="account billing requires authorize_account",
            )
        allowed = await maybe_await(
            self.settings.subscription.authorize_account(
                AccountAuthorizationContext(
                    action=action,
                    account=account,
                    individual=individual,
                    session=session,
                ),
            ),
        )
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not authorized")

    async def _resolve_target_subscription(
        self,
        *,
        action: StripeAction,
        account_id: UUID | None,
        subscription_id: UUID | None,
    ) -> tuple[StripeAccountProtocol, SubscriptionT]:
        if subscription_id is not None:
            subscription = await self.subscription_adapter.get_subscription_by_id(self.client.db, subscription_id)
            if subscription is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
            if account_id is not None and subscription.account_id != account_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
            account = await self._get_authorized_account(action=action, account_id=subscription.account_id)
            return account, subscription

        account = await self._get_authorized_account(action=action, account_id=account_id)
        subscription = await self.subscription_adapter.get_active_subscription(
            self.client.db,
            account_id=account.id,
        )
        if subscription is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
        return account, subscription

    async def _get_plan(self, name: str) -> StripePlan:
        if (plan := await self._find_plan(name)) is not None:
            return plan
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription plan not found")

    async def _find_plan(self, name: str) -> StripePlan | None:
        for plan in await self._get_plans():
            if plan.name.lower() == name.lower():
                return plan
        return None

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

    def _resolve_account_id(self, account_id: UUID | None) -> UUID:
        individual, _session = self._require_authenticated()
        return account_id or individual.id

    def _apply_account_identity(
        self,
        *,
        payload: CustomerCreateParams,
        account: StripeAccountProtocol,
    ) -> None:
        if account.account_type == AccountType.INDIVIDUAL:
            if not isinstance(account, IndividualProtocol):
                msg = "individual account must expose email"
                raise TypeError(msg)
            payload["email"] = account.email
            if account.name is not None:
                payload["name"] = account.name
            return
        if account.name is not None:
            payload["name"] = account.name

    def _validated_url(self, url: str) -> str:
        if (normalized := normalize_relative_or_same_origin_url(url, base_url=self.belgie_settings.base_url)) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="url must be relative or same-origin")
        return normalized

    async def _build_checkout_session_params(  # noqa: PLR0913
        self,
        *,
        extra_params: checkout.SessionCreateParams | None,
        customer_id: str,
        line_items: list[checkout.SessionCreateParamsLineItem],
        redirect_urls: tuple[str, str],
        metadata: dict[str, str],
        locale: StripeSubscriptionLocale | None,
        trial_days: int | None,
        proration_behavior: StripeProrationBehavior | None,
    ) -> checkout.SessionCreateParams:
        success_url, cancel_url = redirect_urls
        payload = _copy_checkout_session_params(extra_params)
        payload["mode"] = "subscription"
        payload["customer"] = customer_id
        payload["line_items"] = line_items
        payload["success_url"] = success_url
        payload["cancel_url"] = cancel_url
        if locale is not None:
            payload["locale"] = locale
        payload["metadata"] = {
            **(payload.get("metadata") or {}),
            **metadata,
        }

        subscription_data = _copy_checkout_subscription_data(payload.get("subscription_data"))
        subscription_data["metadata"] = {
            **(subscription_data.get("metadata") or {}),
            **metadata,
        }
        if trial_days is not None:
            subscription_data["trial_period_days"] = trial_days
        if proration_behavior in {"create_prorations", "none"}:
            subscription_data["proration_behavior"] = proration_behavior
        payload["subscription_data"] = subscription_data
        return payload

    def _build_billing_portal_params(
        self,
        *,
        customer_id: str,
        return_url: str,
        locale: BillingPortalLocale | None,
    ) -> billing_portal.SessionCreateParams:
        payload = billing_portal.SessionCreateParams(
            customer=customer_id,
            return_url=return_url,
        )
        if locale is not None:
            payload["locale"] = locale
        return payload

    def _build_cancel_portal_params(
        self,
        *,
        customer_id: str,
        return_url: str,
        subscription_id: str,
        locale: BillingPortalLocale | None,
    ) -> billing_portal.SessionCreateParams:
        payload = billing_portal.SessionCreateParams(
            customer=customer_id,
            return_url=return_url,
            flow_data=billing_portal.SessionCreateParamsFlowData(
                type="subscription_cancel",
                after_completion=billing_portal.SessionCreateParamsFlowDataAfterCompletion(
                    type="redirect",
                    redirect=billing_portal.SessionCreateParamsFlowDataAfterCompletionRedirect(
                        return_url=return_url,
                    ),
                ),
                subscription_cancel=billing_portal.SessionCreateParamsFlowDataSubscriptionCancel(
                    subscription=subscription_id,
                ),
            ),
        )
        if locale is not None:
            payload["locale"] = locale
        return payload

    def _build_upgrade_portal_params(
        self,
        *,
        customer_id: str,
        return_url: str,
        stripe_subscription: Subscription,
        desired_item: DesiredSubscriptionItem,
        locale: StripeSubscriptionLocale | None,
    ) -> billing_portal.SessionCreateParams:
        if not stripe_subscription.items.data:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe subscription missing items",
            )

        portal_item = billing_portal.SessionCreateParamsFlowDataSubscriptionUpdateConfirmItem(
            id=stripe_subscription.items.data[0].id,
            price=desired_item.price_id,
        )
        if desired_item.quantity is not None:
            portal_item["quantity"] = desired_item.quantity

        payload = billing_portal.SessionCreateParams(
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
                    subscription=stripe_subscription.id,
                    items=[portal_item],
                ),
            ),
        )
        if locale is not None:
            payload["locale"] = locale
        return payload

    async def _schedule_subscription_change(
        self,
        *,
        account: StripeAccountProtocol,
        subscription: SubscriptionT,
        stripe_subscription: Subscription,
        plan: StripePlan,
        desired_items: list[DesiredSubscriptionItem],
    ) -> None:
        if not isinstance(stripe_subscription.current_period_start, int) or not isinstance(
            stripe_subscription.current_period_end,
            int,
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe subscription missing current period timestamps",
            )

        schedule = await self.stripe.v1.subscription_schedules.create_async(
            SubscriptionScheduleCreateParams(
                from_subscription=stripe_subscription.id,
                metadata=schedule_metadata(
                    account=account,
                    subscription_id=subscription.id,
                    plan=plan.name.lower(),
                ),
            ),
        )
        schedule_id = schedule.id
        if schedule_id is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe subscription schedule did not return an id",
            )

        next_phase = SubscriptionScheduleUpdateParamsPhase(
            start_date=stripe_subscription.current_period_end,
            items=self._build_schedule_phase_items(desired_items),
            metadata=subscription_metadata(
                account=account,
                subscription_id=subscription.id,
                plan=plan.name.lower(),
                metadata={},
            ),
        )
        if plan.proration_behavior is not None:
            next_phase["proration_behavior"] = plan.proration_behavior

        await self.stripe.v1.subscription_schedules.update_async(
            schedule_id,
            SubscriptionScheduleUpdateParams(
                end_behavior="release",
                phases=[
                    SubscriptionScheduleUpdateParamsPhase(
                        start_date=stripe_subscription.current_period_start,
                        end_date=stripe_subscription.current_period_end,
                        items=self._build_schedule_phase_items_from_subscription(stripe_subscription),
                    ),
                    next_phase,
                ],
                **({} if plan.proration_behavior is None else {"proration_behavior": plan.proration_behavior}),
            ),
        )
        await self.subscription_adapter.update_subscription(
            self.client.db,
            subscription_id=subscription.id,
            stripe_schedule_id=schedule_id,
        )

    async def _build_desired_subscription_items(
        self,
        *,
        account: StripeAccountProtocol,
        plan: StripePlan,
        base_price_id: str,
        seats: int | None,
    ) -> list[DesiredSubscriptionItem]:
        desired_items: list[DesiredSubscriptionItem] = []
        seat_quantity = await self._resolve_seat_quantity(
            account=account,
            plan=plan,
            requested_seats=seats,
        )

        desired_items.append(
            DesiredSubscriptionItem(
                price_id=base_price_id,
                quantity=None if await self._price_is_metered(base_price_id) else seat_quantity,
            )
            if plan.seat_price_id == base_price_id
            else DesiredSubscriptionItem(
                price_id=base_price_id,
                quantity=None if await self._price_is_metered(base_price_id) else 1,
            ),
        )

        if plan.seat_price_id is not None and plan.seat_price_id != base_price_id:
            desired_items.append(
                DesiredSubscriptionItem(
                    price_id=plan.seat_price_id,
                    quantity=None if await self._price_is_metered(plan.seat_price_id) else seat_quantity,
                ),
            )

        for line_item in plan.line_items:
            if (price_id := line_item.get("price")) is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="stripe plan line_items must use price ids",
                )
            quantity = line_item.get("quantity")
            desired_items.append(
                DesiredSubscriptionItem(
                    price_id=price_id,
                    quantity=None if await self._price_is_metered(price_id) else quantity,
                ),
            )
        return self._dedupe_desired_items(desired_items)

    def _dedupe_desired_items(
        self,
        desired_items: list[DesiredSubscriptionItem],
    ) -> list[DesiredSubscriptionItem]:
        deduped: dict[str, DesiredSubscriptionItem] = {}
        for item in desired_items:
            deduped[item.price_id] = item
        return list(deduped.values())

    async def _resolve_seat_quantity(
        self,
        *,
        account: StripeAccountProtocol,
        plan: StripePlan,
        requested_seats: int | None,
    ) -> int:
        if plan.seat_price_id is not None and account.account_type == AccountType.ORGANIZATION:
            if self.organization_adapter is None:
                return requested_seats or 1
            members = await self.organization_adapter.list_members(
                self.client.db,
                organization_id=account.id,
            )
            return max(1, len(members))
        return requested_seats or 1

    async def _price_is_metered(self, price_id: str) -> bool:
        price = await self.stripe.v1.prices.retrieve_async(price_id)
        return bool(price.recurring and getattr(price.recurring, "usage_type", None) == "metered")

    async def _build_checkout_line_items(
        self,
        desired_items: list[DesiredSubscriptionItem],
    ) -> list[checkout.SessionCreateParamsLineItem]:
        line_items: list[checkout.SessionCreateParamsLineItem] = []
        for desired_item in desired_items:
            line_item = checkout.SessionCreateParamsLineItem(price=desired_item.price_id)
            if desired_item.quantity is not None:
                line_item["quantity"] = desired_item.quantity
            line_items.append(line_item)
        return line_items

    def _build_subscription_update_items(
        self,
        *,
        current_items: list[_SubscriptionItem],
        desired_items: list[DesiredSubscriptionItem],
    ) -> list[SubscriptionUpdateParamsItem]:
        used_current_ids: set[str] = set()
        matched_desired_indexes: set[int] = set()
        update_items: list[SubscriptionUpdateParamsItem] = []

        for index, desired_item in enumerate(desired_items):
            matched_item = next(
                (
                    current_item
                    for current_item in current_items
                    if current_item.id not in used_current_ids and current_item.price.id == desired_item.price_id
                ),
                None,
            )
            if matched_item is None:
                continue
            payload = SubscriptionUpdateParamsItem(id=matched_item.id)
            if desired_item.quantity is not None:
                payload["quantity"] = desired_item.quantity
            update_items.append(payload)
            used_current_ids.add(matched_item.id)
            matched_desired_indexes.add(index)

        unmatched_current_items = [
            current_item for current_item in current_items if current_item.id not in used_current_ids
        ]
        unmatched_desired_items = [
            desired_item for index, desired_item in enumerate(desired_items) if index not in matched_desired_indexes
        ]

        while unmatched_current_items and unmatched_desired_items:
            current_item = unmatched_current_items.pop(0)
            desired_item = unmatched_desired_items.pop(0)
            payload = SubscriptionUpdateParamsItem(id=current_item.id, price=desired_item.price_id)
            if desired_item.quantity is not None:
                payload["quantity"] = desired_item.quantity
            update_items.append(payload)
            used_current_ids.add(current_item.id)

        for desired_item in unmatched_desired_items:
            payload = SubscriptionUpdateParamsItem(price=desired_item.price_id)
            if desired_item.quantity is not None:
                payload["quantity"] = desired_item.quantity
            update_items.append(payload)

        update_items.extend(
            SubscriptionUpdateParamsItem(id=current_item.id, deleted=True) for current_item in unmatched_current_items
        )
        return update_items

    def _build_schedule_phase_items(
        self,
        desired_items: list[DesiredSubscriptionItem],
    ) -> list[SubscriptionScheduleUpdateParamsPhaseItem]:
        phase_items: list[SubscriptionScheduleUpdateParamsPhaseItem] = []
        for desired_item in desired_items:
            phase_item = SubscriptionScheduleUpdateParamsPhaseItem(price=desired_item.price_id)
            if desired_item.quantity is not None:
                phase_item["quantity"] = desired_item.quantity
            phase_items.append(phase_item)
        return phase_items

    def _build_schedule_phase_items_from_subscription(
        self,
        stripe_subscription: Subscription,
    ) -> list[SubscriptionScheduleUpdateParamsPhaseItem]:
        phase_items: list[SubscriptionScheduleUpdateParamsPhaseItem] = []
        for item in stripe_subscription.items.data:
            phase_item = SubscriptionScheduleUpdateParamsPhaseItem(price=item.price.id)
            if (quantity := self._current_item_quantity(item)) is not None:
                phase_item["quantity"] = quantity
            phase_items.append(phase_item)
        return phase_items

    def _subscription_matches_desired_items(
        self,
        *,
        current_items: list[_SubscriptionItem],
        desired_items: list[DesiredSubscriptionItem],
    ) -> bool:
        current_signatures = sorted((item.price.id, self._current_item_quantity(item)) for item in current_items)
        desired_signatures = sorted((item.price_id, item.quantity) for item in desired_items)
        return current_signatures == desired_signatures

    def _current_item_quantity(self, item: _SubscriptionItem) -> int | None:
        recurring = getattr(item.price, "recurring", None)
        if recurring is not None and getattr(recurring, "usage_type", None) == "metered":
            return None
        quantity = getattr(item, "quantity", None)
        return quantity if isinstance(quantity, int) else None

    async def _trial_days_for_checkout(self, *, account_id: UUID, plan: StripePlan) -> int | None:
        if plan.free_trial is None:
            return None
        subscriptions = await self.subscription_adapter.list_subscriptions(
            self.client.db,
            account_id=account_id,
        )
        for subscription in subscriptions:
            if subscription.trial_start is not None or subscription.trial_end is not None:
                return None
            if subscription.status == "trialing":
                return None
        return plan.free_trial.days

    async def _find_existing_customer(self, account: StripeAccountProtocol) -> _HasID | None:
        if account.account_type == AccountType.INDIVIDUAL:
            if not isinstance(account, IndividualProtocol):
                msg = "individual account must expose email"
                raise TypeError(msg)
            return await self._find_existing_individual_customer(account)
        return await self._find_existing_group_customer(account)

    async def _find_existing_individual_customer(
        self,
        account: IndividualProtocol[str],
    ) -> _HasID | None:
        customers: list[_HasID] = []
        try:
            search_result = await self.stripe.v1.customers.search_async(
                CustomerSearchParams(
                    query=f'email:"{escape_stripe_search_value(account.email)}"',
                    limit=10,
                ),
            )
            customers = list(search_result.data)
        except stripe.error.StripeError:
            customers = []
        if not customers:
            list_result = await self.stripe.v1.customers.list_async(
                CustomerListParams(email=account.email, limit=10),
            )
            customers = list(list_result.data)
        return next((customer for customer in customers if self._customer_matches_account(customer, account)), None)

    async def _find_existing_group_customer(self, account: StripeAccountProtocol) -> _HasID | None:
        customers: list[_HasID] = []
        try:
            search_result = await self.stripe.v1.customers.search_async(
                CustomerSearchParams(
                    query=(
                        f'metadata["account_id"]:"{account.id}" AND metadata["account_type"]:"{account.account_type}"'
                    ),
                    limit=10,
                ),
            )
            customers = list(search_result.data)
        except stripe.error.StripeError:
            customers = []
        if not customers:
            list_result = await self.stripe.v1.customers.list_async(CustomerListParams(limit=100))
            customers = list(list_result.data)
        return next((customer for customer in customers if self._customer_matches_account(customer, account)), None)

    def _customer_matches_account(self, customer: _HasID, account: StripeAccountProtocol) -> bool:
        metadata = parse_customer_metadata(_metadata_dict(getattr(customer, "metadata", None)))
        if account.account_type == AccountType.INDIVIDUAL:
            if metadata.account_type in {AccountType.ORGANIZATION, AccountType.TEAM}:
                return False
            return metadata.raw.get("account_id") is None or metadata.account_id == account.id
        return metadata.account_id == account.id and metadata.account_type == account.account_type

    def _coerce_checkout_session_event(self, event: Event) -> CheckoutSession:
        return CheckoutSession.construct_from(event.data.object, key=None)

    def _coerce_subscription_event(self, event: Event) -> Subscription:
        return Subscription.construct_from(event.data.object, key=None)

    async def _lookup_subscription_from_metadata(self, metadata: dict[str, str]) -> SubscriptionT | None:
        parsed_metadata = parse_subscription_metadata(metadata)
        if (
            parsed_metadata.raw.get("local_subscription_id") is not None
            and parsed_metadata.local_subscription_id is None
        ):
            detail = "stripe metadata local_subscription_id must be a valid UUID"
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
        if parsed_metadata.local_subscription_id is None:
            return None
        return await self.subscription_adapter.get_subscription_by_id(
            self.client.db,
            parsed_metadata.local_subscription_id,
        )

    async def _sync_subscription(
        self,
        *,
        stripe_subscription: Subscription,
        event_type: str,
        existing_subscription: SubscriptionT | None,
        checkout_session: CheckoutSession | None = None,
    ) -> SubscriptionT | None:
        metadata = _metadata_dict(stripe_subscription.metadata)
        prior_subscription = existing_subscription or await self._lookup_subscription_from_metadata(metadata)
        account = await self._resolve_sync_account(metadata=metadata, subscription=prior_subscription)
        if account is None:
            return None

        plan = await self._match_plan(
            plan_name=metadata.get("plan"),
            stripe_subscription=stripe_subscription,
            existing_subscription=prior_subscription,
        )
        recurring = self._extract_primary_recurring(stripe_subscription, plan=plan)
        stripe_customer_id = _expandable_id(stripe_subscription.customer)
        period_start = self._timestamp_to_datetime(getattr(stripe_subscription, "current_period_start", None))
        period_end = self._timestamp_to_datetime(getattr(stripe_subscription, "current_period_end", None))
        trial_start = self._timestamp_to_datetime(getattr(stripe_subscription, "trial_start", None))
        trial_end = self._timestamp_to_datetime(getattr(stripe_subscription, "trial_end", None))
        cancel_at = self._timestamp_to_datetime(stripe_subscription.cancel_at)
        canceled_at = self._timestamp_to_datetime(stripe_subscription.canceled_at)
        ended_at = self._timestamp_to_datetime(stripe_subscription.ended_at)
        normalized_status = self._normalize_status(stripe_subscription.status)
        seats = self._extract_seat_count(stripe_subscription, plan=plan)
        stripe_schedule_id = self._plugin_schedule_id(
            stripe_subscription=stripe_subscription,
            existing_subscription=prior_subscription,
        )

        local_plan_name = (
            plan.name.lower()
            if plan is not None
            else (prior_subscription.plan if prior_subscription is not None else None)
        )
        if local_plan_name is None:
            return None

        if prior_subscription is None:
            subscription = await self.subscription_adapter.create_subscription(
                self.client.db,
                plan=local_plan_name,
                account_id=account.id,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription.id,
                status=normalized_status,
                period_start=period_start,
                period_end=period_end,
                trial_start=trial_start,
                trial_end=trial_end,
                seats=seats,
                cancel_at_period_end=stripe_subscription.cancel_at_period_end,
                cancel_at=cancel_at,
                canceled_at=canceled_at,
                ended_at=ended_at,
                billing_interval=recurring,
                stripe_schedule_id=stripe_schedule_id,
            )
        else:
            updated = await self.subscription_adapter.update_subscription(
                self.client.db,
                subscription_id=prior_subscription.id,
                plan=local_plan_name,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription.id,
                status=normalized_status,
                period_start=period_start,
                period_end=period_end,
                trial_start=trial_start,
                trial_end=trial_end,
                seats=seats,
                cancel_at_period_end=stripe_subscription.cancel_at_period_end,
                cancel_at=cancel_at,
                canceled_at=canceled_at,
                ended_at=ended_at,
                billing_interval=recurring,
                stripe_schedule_id=stripe_schedule_id,
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
            account=account,
            checkout_session=checkout_session,
            cancellation_details=getattr(stripe_subscription, "cancellation_details", None),
        )
        await self._run_subscription_hooks(
            event_type=event_type,
            prior_subscription=prior_subscription,
            hook_context=hook_context,
        )
        return subscription

    async def _run_subscription_hooks(
        self,
        *,
        event_type: str,
        prior_subscription: SubscriptionT | None,
        hook_context: SubscriptionEventContext[SubscriptionT, StripeAccountProtocol],
    ) -> None:
        match event_type:
            case "checkout.session.completed":
                await self._run_checkout_completed_hooks(
                    prior_subscription=prior_subscription,
                    hook_context=hook_context,
                )
            case "customer.subscription.created":
                await self._run_subscription_created_hooks(
                    prior_subscription=prior_subscription,
                    hook_context=hook_context,
                )
            case "customer.subscription.updated":
                await self._run_subscription_updated_hooks(
                    prior_subscription=prior_subscription,
                    hook_context=hook_context,
                )
            case "customer.subscription.deleted":
                await self._run_subscription_deleted_hooks(hook_context=hook_context)

    async def _run_checkout_completed_hooks(
        self,
        *,
        prior_subscription: SubscriptionT | None,
        hook_context: SubscriptionEventContext[SubscriptionT, StripeAccountProtocol],
    ) -> None:
        await self._run_trial_start_hook(
            event_type="checkout.session.completed",
            prior_subscription=prior_subscription,
            hook_context=hook_context,
        )
        if (
            hook_context.checkout_session is not None
            and hook_context.plan is not None
            and self.settings.subscription.on_subscription_complete is not None
        ):
            await maybe_await(self.settings.subscription.on_subscription_complete(hook_context))

    async def _run_subscription_created_hooks(
        self,
        *,
        prior_subscription: SubscriptionT | None,
        hook_context: SubscriptionEventContext[SubscriptionT, StripeAccountProtocol],
    ) -> None:
        if prior_subscription is None and self.settings.subscription.on_subscription_created is not None:
            await maybe_await(self.settings.subscription.on_subscription_created(hook_context))
        await self._run_trial_start_hook(
            event_type="customer.subscription.created",
            prior_subscription=prior_subscription,
            hook_context=hook_context,
        )

    async def _run_subscription_updated_hooks(
        self,
        *,
        prior_subscription: SubscriptionT | None,
        hook_context: SubscriptionEventContext[SubscriptionT, StripeAccountProtocol],
    ) -> None:
        if (
            self.settings.subscription.on_subscription_cancel_requested is not None
            and self._is_pending_cancellation_transition(
                prior_subscription=prior_subscription,
                stripe_subscription=hook_context.raw_event,
            )
        ):
            await maybe_await(self.settings.subscription.on_subscription_cancel_requested(hook_context))
        if self.settings.subscription.on_subscription_updated is not None:
            await maybe_await(self.settings.subscription.on_subscription_updated(hook_context))
        await self._run_trial_update_hooks(
            prior_subscription=prior_subscription,
            hook_context=hook_context,
        )

    async def _run_subscription_deleted_hooks(
        self,
        *,
        hook_context: SubscriptionEventContext[SubscriptionT, StripeAccountProtocol],
    ) -> None:
        if self.settings.subscription.on_subscription_deleted is not None:
            await maybe_await(self.settings.subscription.on_subscription_deleted(hook_context))
        if self.settings.subscription.on_subscription_canceled is not None:
            await maybe_await(self.settings.subscription.on_subscription_canceled(hook_context))

    async def _run_trial_start_hook(
        self,
        *,
        event_type: str,
        prior_subscription: SubscriptionT | None,
        hook_context: SubscriptionEventContext[SubscriptionT, StripeAccountProtocol],
    ) -> None:
        free_trial = None if hook_context.plan is None else hook_context.plan.free_trial
        if (
            free_trial is None
            or free_trial.on_trial_start is None
            or not self._is_trial_start_transition(
                event_type=event_type,
                prior_subscription=prior_subscription,
                subscription=hook_context.subscription,
                checkout_session=hook_context.checkout_session,
            )
        ):
            return
        await maybe_await(free_trial.on_trial_start(hook_context))

    async def _run_trial_update_hooks(
        self,
        *,
        prior_subscription: SubscriptionT | None,
        hook_context: SubscriptionEventContext[SubscriptionT, StripeAccountProtocol],
    ) -> None:
        free_trial = None if hook_context.plan is None else hook_context.plan.free_trial
        if free_trial is None or prior_subscription is None or prior_subscription.status != "trialing":
            return
        if hook_context.subscription.status == "active" and free_trial.on_trial_end is not None:
            await maybe_await(free_trial.on_trial_end(hook_context))
        if hook_context.subscription.status == "incomplete_expired" and free_trial.on_trial_expired is not None:
            await maybe_await(free_trial.on_trial_expired(hook_context))

    def _is_trial_start_transition(
        self,
        *,
        event_type: str,
        prior_subscription: SubscriptionT | None,
        subscription: SubscriptionT,
        checkout_session: CheckoutSession | None,
    ) -> bool:
        if event_type == "checkout.session.completed" and checkout_session is None:
            return False
        if event_type not in {"checkout.session.completed", "customer.subscription.created"}:
            return False
        had_trial = prior_subscription is not None and (
            prior_subscription.trial_start is not None or prior_subscription.trial_end is not None
        )
        has_trial = subscription.trial_start is not None or subscription.trial_end is not None
        return has_trial and not had_trial

    def _is_pending_cancellation_transition(
        self,
        *,
        prior_subscription: SubscriptionT | None,
        stripe_subscription: Subscription,
    ) -> bool:
        return self._stripe_subscription_is_pending_cancellation(stripe_subscription) and not (
            prior_subscription is not None and self._subscription_is_pending_cancellation(prior_subscription)
        )

    async def _resolve_sync_account(
        self,
        *,
        metadata: dict[str, str],
        subscription: SubscriptionT | None,
    ) -> StripeAccountProtocol | None:
        parsed_metadata = parse_subscription_metadata(metadata)
        if parsed_metadata.raw.get("account_id") is not None and parsed_metadata.account_id is None:
            detail = "stripe metadata account_id must be a valid UUID"
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
        account_id = parsed_metadata.account_id or (None if subscription is None else subscription.account_id)
        if account_id is None:
            return None
        return await self.client.adapter.get_account_by_id(self.client.db, account_id)

    async def _match_plan(
        self,
        *,
        plan_name: str | None,
        stripe_subscription: Subscription,
        existing_subscription: SubscriptionT | None,
    ) -> StripePlan | None:
        if plan_name is not None and (plan := await self._find_plan(plan_name)) is not None:
            return plan
        if (
            existing_subscription is not None
            and (plan := await self._find_plan(existing_subscription.plan)) is not None
        ):
            return plan
        for plan in await self._get_plans():
            if self._subscription_matches_plan(stripe_subscription, plan=plan):
                return plan
        return None

    def _subscription_matches_plan(self, stripe_subscription: Subscription, *, plan: StripePlan) -> bool:
        for item in stripe_subscription.items.data:
            price = item.price
            if price.id is not None and price.id in {plan.price_id, plan.annual_price_id}:
                return True
            if price.lookup_key is not None and price.lookup_key in {plan.lookup_key, plan.annual_lookup_key}:
                return True
        return False

    def _resolve_plan_item(
        self,
        stripe_subscription: Subscription,
        *,
        plan: StripePlan,
    ) -> _SubscriptionItem | None:
        for item in stripe_subscription.items.data:
            price = item.price
            if price.id is not None and price.id in {plan.price_id, plan.annual_price_id}:
                return item
            if price.lookup_key is not None and price.lookup_key in {plan.lookup_key, plan.annual_lookup_key}:
                return item
        if len(stripe_subscription.items.data) == 1:
            return stripe_subscription.items.data[0]
        return None

    def _extract_primary_recurring(
        self,
        stripe_subscription: Subscription,
        *,
        plan: StripePlan | None,
    ) -> StripeBillingInterval | None:
        if plan is not None and (plan_item := self._resolve_plan_item(stripe_subscription, plan=plan)) is not None:
            recurring = plan_item.price.recurring
            if recurring is not None:
                return self._normalize_billing_interval(recurring.interval)
        for item in stripe_subscription.items.data:
            if (recurring := item.price.recurring) is not None:
                return self._normalize_billing_interval(recurring.interval)
        return None

    def _extract_seat_count(
        self,
        stripe_subscription: Subscription,
        *,
        plan: StripePlan | None,
    ) -> int | None:
        if plan is None:
            return None
        if plan.seat_price_id is None:
            if (plan_item := self._resolve_plan_item(stripe_subscription, plan=plan)) is not None:
                return self._current_item_quantity(plan_item)
            return None
        if (
            plan_item := self._resolve_plan_item(stripe_subscription, plan=plan)
        ) is not None and plan_item.price.id == plan.seat_price_id:
            return self._current_item_quantity(plan_item)
        for item in stripe_subscription.items.data:
            if item.price.id == plan.seat_price_id:
                return self._current_item_quantity(item)
        return None

    def _plugin_schedule_id(
        self,
        *,
        stripe_subscription: Subscription,
        existing_subscription: SubscriptionT | None,
    ) -> str | None:
        schedule = getattr(stripe_subscription, "schedule", None)
        schedule_id = _expandable_id(schedule)
        if schedule_id is None:
            return None
        if existing_subscription is not None and existing_subscription.stripe_schedule_id == schedule_id:
            return schedule_id
        if isinstance(schedule, StripeObject):
            parsed_schedule = parse_schedule_metadata(_metadata_dict(getattr(schedule, "metadata", None)))
            if parsed_schedule.is_managed_by_plugin:
                return schedule_id
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

    async def _resolve_view_price_id(
        self,
        *,
        plan: StripePlan | None,
        subscription: SubscriptionT,
    ) -> str | None:
        if plan is None:
            return None
        try:
            return await self._resolve_price_id(
                plan=plan,
                annual=subscription.billing_interval == "year",
            )
        except HTTPException:
            return None

    async def _sync_checkout_session(self, checkout_session_id: str) -> None:
        try:
            checkout_session = await self.stripe.v1.checkout.sessions.retrieve_async(checkout_session_id)
        except stripe.error.StripeError:
            return
        subscription_id = _expandable_id(checkout_session.subscription)
        if subscription_id is None:
            return
        local_subscription = await self._lookup_subscription_from_metadata(_metadata_dict(checkout_session.metadata))
        stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(subscription_id)
        await self._sync_subscription(
            stripe_subscription=stripe_subscription,
            event_type="checkout.session.completed",
            existing_subscription=local_subscription,
        )

    def _should_sync_pending_cancellation(self, exc: Exception) -> bool:
        detail = str(exc).casefold()
        return any(
            marker in detail
            for marker in (
                "already set to be canceled",
                "already scheduled to cancel",
                "already canceled",
                "pending cancellation",
            )
        )

    async def _sync_pending_cancellation_from_stripe(self, *, subscription: SubscriptionT) -> None:
        if subscription.stripe_subscription_id is None:
            return
        try:
            stripe_subscription = await self.stripe.v1.subscriptions.retrieve_async(subscription.stripe_subscription_id)
        except stripe.error.StripeError:
            return
        if not self._stripe_subscription_is_pending_cancellation(stripe_subscription):
            return
        await self._sync_subscription(
            stripe_subscription=stripe_subscription,
            event_type="customer.subscription.updated",
            existing_subscription=subscription,
        )

    def _subscription_is_pending_cancellation(self, subscription: SubscriptionT) -> bool:
        return bool(
            subscription.cancel_at_period_end
            or subscription.cancel_at is not None
            or subscription.canceled_at is not None,
        )

    def _stripe_subscription_is_pending_cancellation(self, stripe_subscription: Subscription) -> bool:
        return bool(
            stripe_subscription.cancel_at_period_end
            or isinstance(stripe_subscription.cancel_at, int)
            or getattr(stripe_subscription, "cancellation_details", None) is not None
            or isinstance(stripe_subscription.canceled_at, int),
        )

    async def _release_plugin_schedule_if_present(self, subscription: SubscriptionT) -> SubscriptionT:
        if subscription.stripe_schedule_id is None:
            return subscription
        return await self._release_plugin_schedule(subscription)

    async def _release_plugin_schedule(self, subscription: SubscriptionT) -> SubscriptionT:
        if subscription.stripe_schedule_id is None:
            return subscription
        await self.stripe.v1.subscription_schedules.release_async(
            subscription.stripe_schedule_id,
            SubscriptionScheduleReleaseParams(),
        )
        updated = await self.subscription_adapter.update_subscription(
            self.client.db,
            subscription_id=subscription.id,
            stripe_schedule_id=None,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="failed to update subscription",
            )
        return updated

    def _is_annual_subscription(
        self,
        *,
        subscription: SubscriptionT,
        stripe_subscription: Subscription,
        plan: StripePlan,
    ) -> bool:
        if subscription.billing_interval == "year":
            return True
        for item in stripe_subscription.items.data:
            if plan.annual_price_id is not None and item.price.id == plan.annual_price_id:
                return True
            if plan.annual_lookup_key is not None and item.price.lookup_key == plan.annual_lookup_key:
                return True
        return False

    def _require_authenticated(self) -> tuple[IndividualProtocol[str], SessionProtocol]:
        if self.current_individual is None or self.current_session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
        return self.current_individual, self.current_session
