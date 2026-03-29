from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from belgie_proto.stripe import (
    StripeOrganizationProtocol,
    StripeSubscriptionProtocol,
    StripeUserProtocol,
)
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from belgie_stripe.models import (
    BillingPortalRequest,
    CancelSubscriptionRequest,
    CheckoutSessionContext,
    CustomerCreateContext,
    ListSubscriptionsRequest,
    ReferenceAuthorizationContext,
    RestoreSubscriptionRequest,
    StripePlan,
    StripeRedirectResponse,
    SubscriptionEventContext,
    SubscriptionView,
    UpgradeSubscriptionRequest,
)
from belgie_stripe.utils import (
    absolute_url,
    append_query_params,
    call_external,
    maybe_await,
    normalize_relative_or_same_origin_url,
    sign_success_token,
    stripe_bool,
    stripe_iterable,
    stripe_mapping,
    stripe_str,
    stripe_value,
    unsign_success_token,
)

if TYPE_CHECKING:
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.core.session import SessionProtocol
    from belgie_proto.organization import (
        InvitationProtocol,
        MemberProtocol,
        OrganizationAdapterProtocol,
        OrganizationProtocol,
    )
    from belgie_proto.stripe import StripeAdapterProtocol, StripeSubscriptionStatus

    from belgie_stripe.settings import Stripe


SUCCESS_POLL_ATTEMPTS = 20
SUCCESS_POLL_INTERVAL_SECONDS = 0.05
SUCCESSFUL_SUBSCRIPTION_STATUSES = ("active", "past_due", "paused", "trialing", "unpaid")
TERMINAL_SUBSCRIPTION_STATUSES = ("canceled", "incomplete_expired")


@dataclass(slots=True, kw_only=True)
class StripeClient[
    SubscriptionT: StripeSubscriptionProtocol,
]:
    client: BelgieClient
    belgie_settings: BelgieSettings
    settings: Stripe[SubscriptionT]
    current_user: StripeUserProtocol[str] | None = None
    current_session: SessionProtocol | None = None
    organization_adapter: (
        OrganizationAdapterProtocol[OrganizationProtocol, MemberProtocol, InvitationProtocol] | None
    ) = None

    @property
    def subscription_adapter(self) -> StripeAdapterProtocol[SubscriptionT]:
        return self.settings.subscription.adapter

    @property
    def stripe(self) -> object:
        return self.settings.stripe

    async def upgrade(
        self,
        *,
        data: UpgradeSubscriptionRequest,
    ) -> StripeRedirectResponse:
        user, session = self._require_authenticated()
        if self.settings.subscription.require_email_verification and user.email_verified_at is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email verification required")

        plan = await self._get_plan(data.plan)
        reference_id = self._resolve_reference_id(reference_id=data.reference_id, customer_type=data.customer_type)
        await self._authorize_reference(
            action="upgrade-subscription",
            reference_id=reference_id,
            customer_type=data.customer_type,
        )

        success_url = self._validated_url(data.success_url)
        cancel_url = self._validated_url(data.cancel_url)
        return_url = self._validated_url(data.return_url) if data.return_url else success_url

        active_subscription = await self.subscription_adapter.get_active_subscription(
            self.client.db,
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        if (
            active_subscription
            and active_subscription.plan.lower() == plan.name.lower()
            and (billing_interval := active_subscription.billing_interval) is not None
            and ((data.annual and billing_interval == "year") or (not data.annual and billing_interval != "year"))
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already subscribed to this plan")

        customer_id = active_subscription.stripe_customer_id if active_subscription else None
        if customer_id is None:
            customer_id = await self._ensure_customer(
                customer_type=data.customer_type,
                reference_id=reference_id,
                metadata=data.metadata,
            )

        price_id = await self._resolve_price_id(plan=plan, annual=data.annual)
        if active_subscription and active_subscription.stripe_subscription_id:
            payload = {
                "customer": customer_id,
                "return_url": absolute_url(self.belgie_settings.base_url, return_url),
                "flow_data": {
                    "type": "subscription_update_confirm",
                    "after_completion": {
                        "type": "redirect",
                        "redirect": {"return_url": absolute_url(self.belgie_settings.base_url, return_url)},
                    },
                    "subscription_update_confirm": {
                        "subscription": active_subscription.stripe_subscription_id,
                        "items": [{"price": price_id}],
                    },
                },
            }
            portal_session = await call_external(self.stripe.billing_portal.Session.create, **payload)
            url = stripe_str(portal_session, "url")
            if url is None:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="stripe portal session did not return a url",
                )
            return StripeRedirectResponse(url=url, redirect=not data.disable_redirect)

        pending_subscription = await self.subscription_adapter.get_incomplete_subscription(
            self.client.db,
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        if pending_subscription is None:
            subscription = await self.subscription_adapter.create_subscription(
                self.client.db,
                plan=plan.name.lower(),
                reference_id=reference_id,
                customer_type=data.customer_type,
                stripe_customer_id=customer_id,
            )
        else:
            subscription = await self.subscription_adapter.update_subscription(
                self.client.db,
                subscription_id=pending_subscription.id,
                plan=plan.name.lower(),
                stripe_customer_id=customer_id,
            )
            if subscription is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="failed to update subscription",
                )

        internal_metadata = {
            "local_subscription_id": str(subscription.id),
            "reference_id": str(reference_id),
            "customer_type": data.customer_type,
            "plan": plan.name.lower(),
        }
        checkout_context = CheckoutSessionContext(
            customer_type=data.customer_type,
            reference_id=reference_id,
            plan=plan,
            subscription=subscription,
            user=user,
            session=session,
        )
        extra_params = (
            await maybe_await(self.settings.subscription.get_checkout_session_params(checkout_context))
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
        base_payload = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": internal_success_url,
            "cancel_url": absolute_url(self.belgie_settings.base_url, cancel_url),
            "metadata": {
                **data.metadata,
                **internal_metadata,
            },
            "subscription_data": {
                "metadata": dict(internal_metadata),
            },
        }
        payload = {**(extra_params or {}), **base_payload}
        checkout_session = await call_external(self.stripe.checkout.Session.create, **payload)
        url = stripe_str(checkout_session, "url")
        if url is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe checkout session did not return a url",
            )
        return StripeRedirectResponse(url=url, redirect=not data.disable_redirect)

    async def list_subscriptions(self, *, data: ListSubscriptionsRequest) -> list[SubscriptionView]:
        reference_id = self._resolve_reference_id(reference_id=data.reference_id, customer_type=data.customer_type)
        await self._authorize_reference(
            action="list-subscription",
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        subscriptions = await self.subscription_adapter.list_subscriptions(
            self.client.db,
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        return [SubscriptionView.from_subscription(subscription) for subscription in subscriptions]

    async def cancel(
        self,
        *,
        data: CancelSubscriptionRequest,
    ) -> StripeRedirectResponse:
        reference_id = self._resolve_reference_id(reference_id=data.reference_id, customer_type=data.customer_type)
        await self._authorize_reference(
            action="cancel-subscription",
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        customer_id = await self._ensure_customer(
            customer_type=data.customer_type,
            reference_id=reference_id,
            metadata={},
        )
        portal_session = await call_external(
            self.stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=(
                absolute_url(self.belgie_settings.base_url, self._validated_url(data.return_url))
                if data.return_url
                else absolute_url(self.belgie_settings.base_url, "/")
            ),
        )
        url = stripe_str(portal_session, "url")
        if url is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe portal session did not return a url",
            )
        return StripeRedirectResponse(url=url, redirect=not data.disable_redirect)

    async def restore(self, *, data: RestoreSubscriptionRequest) -> SubscriptionView:
        reference_id = self._resolve_reference_id(reference_id=data.reference_id, customer_type=data.customer_type)
        await self._authorize_reference(
            action="restore-subscription",
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        subscription = await self.subscription_adapter.get_active_subscription(
            self.client.db,
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        if subscription is None or subscription.stripe_subscription_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
        if not subscription.cancel_at_period_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="subscription is not pending cancellation",
            )

        stripe_subscription = await call_external(
            self.stripe.Subscription.modify,
            subscription.stripe_subscription_id,
            cancel_at_period_end=False,
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
        reference_id = self._resolve_reference_id(reference_id=data.reference_id, customer_type=data.customer_type)
        await self._authorize_reference(
            action="billing-portal",
            reference_id=reference_id,
            customer_type=data.customer_type,
        )
        customer_id = await self._ensure_customer(
            customer_type=data.customer_type,
            reference_id=reference_id,
            metadata={},
        )
        portal_session = await call_external(
            self.stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=(
                absolute_url(self.belgie_settings.base_url, self._validated_url(data.return_url))
                if data.return_url
                else absolute_url(self.belgie_settings.base_url, "/")
            ),
        )
        url = stripe_str(portal_session, "url")
        if url is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe portal session did not return a url",
            )
        return StripeRedirectResponse(url=url, redirect=not data.disable_redirect)

    async def handle_webhook(self, *, request: Request) -> dict[str, bool]:  # noqa: C901
        payload = await request.body()
        signature = request.headers.get("stripe-signature")
        if signature is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing stripe-signature header")
        event = await call_external(
            self.stripe.Webhook.construct_event,
            payload,
            signature,
            self.settings.stripe_webhook_secret,
        )
        if self.settings.on_event is not None:
            await maybe_await(self.settings.on_event(event))

        event_type = stripe_str(event, "type")
        if event_type is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="stripe event missing type")
        event_data = stripe_mapping(event, "data")
        if event_data is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="stripe event missing data")
        event_object = stripe_mapping(event_data, "object")
        if event_object is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="stripe event missing object")

        if event_type == "checkout.session.completed":
            subscription_id = stripe_str(event_object, "subscription")
            metadata = stripe_mapping(event_object, "metadata") or {}
            local_subscription_id = metadata.get("local_subscription_id")
            local_subscription = None
            if isinstance(local_subscription_id, str):
                parsed_subscription_id = self._coerce_stripe_uuid(
                    local_subscription_id,
                    field_name="local_subscription_id",
                )
                local_subscription = await self.subscription_adapter.get_subscription_by_id(
                    self.client.db,
                    parsed_subscription_id,
                )
            if subscription_id is not None:
                stripe_subscription = await call_external(self.stripe.Subscription.retrieve, subscription_id)
                await self._sync_subscription(
                    stripe_subscription=stripe_subscription,
                    event_type=event_type,
                    existing_subscription=local_subscription,
                )
        elif event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            existing_subscription = None
            stripe_subscription_id = stripe_str(event_object, "id")
            if stripe_subscription_id is not None:
                existing_subscription = await self.subscription_adapter.get_subscription_by_stripe_subscription_id(
                    self.client.db,
                    stripe_subscription_id=stripe_subscription_id,
                )
            await self._sync_subscription(
                stripe_subscription=event_object,
                event_type=event_type,
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

    async def ensure_user_customer(
        self,
        *,
        metadata: dict[str, str],
    ) -> str:
        user = self._require_user()
        if user.stripe_customer_id:
            return user.stripe_customer_id

        context = CustomerCreateContext(
            customer_type="user",
            reference_id=user.id,
            target=user,
            stripe_customer_id="",
            metadata=metadata,
        )
        extra_params = (
            await maybe_await(self.settings.get_customer_create_params(context))
            if self.settings.get_customer_create_params
            else None
        )
        payload = {
            "email": user.email,
            "name": user.name,
            "metadata": {
                "customer_type": "user",
                "reference_id": str(user.id),
                **metadata,
            },
        }
        payload.update(extra_params or {})
        customer = await call_external(self.stripe.Customer.create, **payload)
        customer_id = stripe_str(customer, "id")
        if customer_id is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe customer creation did not return an id",
            )
        await self.client.adapter.update_user(self.client.db, user.id, stripe_customer_id=customer_id)
        if self.settings.on_customer_create is not None:
            await maybe_await(
                self.settings.on_customer_create(
                    CustomerCreateContext(
                        customer_type="user",
                        reference_id=user.id,
                        target=user,
                        stripe_customer_id=customer_id,
                        metadata=metadata,
                    ),
                ),
            )
        return customer_id

    async def ensure_organization_customer(
        self,
        *,
        reference_id: UUID,
        metadata: dict[str, str],
    ) -> str:
        if (
            not self.settings.organization
            or not self.settings.organization.enabled
            or self.organization_adapter is None
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization billing is not enabled")
        organization = await self.organization_adapter.get_organization_by_id(self.client.db, reference_id)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
        if not isinstance(organization, StripeOrganizationProtocol):
            msg = "organization model must expose stripe_customer_id"
            raise TypeError(msg)
        if organization.stripe_customer_id:
            return organization.stripe_customer_id

        context = CustomerCreateContext(
            customer_type="organization",
            reference_id=reference_id,
            target=organization,
            stripe_customer_id="",
            metadata=metadata,
        )
        extra_params = (
            await maybe_await(self.settings.organization.get_customer_create_params(context))
            if self.settings.organization.get_customer_create_params
            else None
        )
        payload = {
            "name": organization.name,
            "metadata": {
                "customer_type": "organization",
                "reference_id": str(reference_id),
                **metadata,
            },
        }
        payload.update(extra_params or {})
        customer = await call_external(self.stripe.Customer.create, **payload)
        customer_id = stripe_str(customer, "id")
        if customer_id is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe customer creation did not return an id",
            )
        await self.organization_adapter.update_organization(
            self.client.db,
            reference_id,
            stripe_customer_id=customer_id,
        )
        if self.settings.organization.on_customer_create is not None:
            await maybe_await(
                self.settings.organization.on_customer_create(
                    CustomerCreateContext(
                        customer_type="organization",
                        reference_id=reference_id,
                        target=organization,
                        stripe_customer_id=customer_id,
                        metadata=metadata,
                    ),
                ),
            )
        return customer_id

    async def _ensure_customer(
        self,
        *,
        customer_type: str,
        reference_id: UUID,
        metadata: dict[str, str],
    ) -> str:
        if customer_type == "organization":
            return await self.ensure_organization_customer(reference_id=reference_id, metadata=metadata)
        return await self.ensure_user_customer(metadata=metadata)

    async def _authorize_reference(
        self,
        *,
        action: str,
        reference_id: UUID,
        customer_type: str,
    ) -> None:
        user, session = self._require_authenticated()
        if customer_type == "user":
            if reference_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="cannot manage another user's subscription",
                )
            return
        if self.settings.subscription.authorize_reference is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization billing requires authorize_reference",
            )
        allowed = await maybe_await(
            self.settings.subscription.authorize_reference(
                ReferenceAuthorizationContext(
                    action=action,
                    customer_type="organization",
                    reference_id=reference_id,
                    user=user,
                    session=session,
                ),
            ),
        )
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not authorized")

    async def _get_plan(self, name: str) -> StripePlan:
        plans = await self._get_plans()
        for plan in plans:
            if plan.name.lower() == name.lower():
                return plan
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription plan not found")

    async def _get_plans(self) -> list[StripePlan]:
        plans = self.settings.subscription.plans
        if callable(plans):
            return await maybe_await(plans())
        return plans

    async def _resolve_price_id(self, *, plan: StripePlan, annual: bool) -> str:
        if annual and plan.annual_price_id:
            return plan.annual_price_id
        if annual and plan.annual_lookup_key:
            return await self._resolve_lookup_key(plan.annual_lookup_key)
        if plan.price_id:
            return plan.price_id
        if plan.lookup_key:
            return await self._resolve_lookup_key(plan.lookup_key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="plan is missing a stripe price")

    async def _resolve_lookup_key(self, lookup_key: str) -> str:
        price_list = await call_external(self.stripe.Price.list, lookup_keys=[lookup_key], active=True, limit=1)
        for price in stripe_iterable(price_list, "data"):
            price_id = stripe_str(price, "id")
            if price_id is not None:
                return price_id
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="stripe price not found")

    def _resolve_reference_id(self, *, reference_id: UUID | None, customer_type: str) -> UUID:
        user, _session = self._require_authenticated()
        if customer_type == "organization":
            if reference_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="reference_id is required for organization billing",
                )
            return reference_id
        return reference_id or user.id

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

    async def _sync_subscription(  # noqa: C901, PLR0912, PLR0915
        self,
        *,
        stripe_subscription: object,
        event_type: str,
        existing_subscription: SubscriptionT | None,
    ) -> SubscriptionT:
        metadata = stripe_mapping(stripe_subscription, "metadata") or {}
        metadata_subscription_id = metadata.get("local_subscription_id")
        subscription = existing_subscription
        if isinstance(metadata_subscription_id, str):
            parsed_subscription_id = self._coerce_stripe_uuid(
                metadata_subscription_id,
                field_name="local_subscription_id",
            )
            if subscription is None:
                subscription = await self.subscription_adapter.get_subscription_by_id(
                    self.client.db,
                    parsed_subscription_id,
                )

        customer_type = metadata.get("customer_type")
        reference_id_raw = metadata.get("reference_id")
        if not isinstance(customer_type, str) or customer_type not in {"user", "organization"}:
            if subscription is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="stripe subscription metadata missing customer_type",
                )
            customer_type = subscription.customer_type
        if isinstance(reference_id_raw, str):
            reference_id = self._coerce_stripe_uuid(reference_id_raw, field_name="reference_id")
        elif subscription is not None:
            reference_id = subscription.reference_id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="stripe subscription metadata missing reference_id",
            )

        plan_name = metadata.get("plan") if isinstance(metadata.get("plan"), str) else None
        plan = await self._match_plan(plan_name=plan_name, stripe_subscription=stripe_subscription)
        stripe_subscription_id = stripe_str(stripe_subscription, "id")
        if stripe_subscription_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="stripe subscription missing id")
        stripe_customer_id = stripe_str(stripe_subscription, "customer")
        status_value = stripe_str(stripe_subscription, "status")
        if status_value is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="stripe subscription missing status")

        recurring = self._extract_primary_recurring(stripe_subscription)
        cancel_at_period_end = stripe_bool(stripe_subscription, "cancel_at_period_end") or False
        period_start = self._timestamp_to_datetime(stripe_value(stripe_subscription, "current_period_start"))
        period_end = self._timestamp_to_datetime(stripe_value(stripe_subscription, "current_period_end"))
        cancel_at = self._timestamp_to_datetime(stripe_value(stripe_subscription, "cancel_at"))
        canceled_at = self._timestamp_to_datetime(stripe_value(stripe_subscription, "canceled_at"))
        ended_at = self._timestamp_to_datetime(stripe_value(stripe_subscription, "ended_at"))

        if subscription is None:
            subscription = await self.subscription_adapter.create_subscription(
                self.client.db,
                plan=plan.name.lower(),
                reference_id=reference_id,
                customer_type=customer_type,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                status=self._normalize_status(status_value),
                period_start=period_start,
                period_end=period_end,
                cancel_at_period_end=cancel_at_period_end,
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
                stripe_subscription_id=stripe_subscription_id,
                status=self._normalize_status(status_value),
                period_start=period_start,
                period_end=period_end,
                cancel_at_period_end=cancel_at_period_end,
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

    async def _match_plan(self, *, plan_name: str | None, stripe_subscription: object) -> StripePlan:
        if plan_name is not None:
            return await self._get_plan(plan_name)
        plans = await self._get_plans()
        items = stripe_mapping(stripe_subscription, "items")
        for item in stripe_iterable(items or {}, "data"):
            price = stripe_mapping(item, "price")
            if price is None:
                continue
            price_id = stripe_str(price, "id")
            lookup_key = stripe_str(price, "lookup_key")
            for plan in plans:
                if price_id in {plan.price_id, plan.annual_price_id}:
                    return plan
                if lookup_key in {plan.lookup_key, plan.annual_lookup_key}:
                    return plan
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription plan not found")

    def _extract_primary_recurring(self, stripe_subscription: object) -> str | None:
        items = stripe_mapping(stripe_subscription, "items")
        for item in stripe_iterable(items or {}, "data"):
            price = stripe_mapping(item, "price")
            recurring = stripe_mapping(price or {}, "recurring")
            interval = stripe_str(recurring or {}, "interval")
            if interval is not None:
                return interval
        return None

    def _normalize_status(self, status_value: str) -> StripeSubscriptionStatus:
        allowed_statuses = {
            "active",
            "canceled",
            "incomplete",
            "incomplete_expired",
            "past_due",
            "paused",
            "trialing",
            "unpaid",
        }
        if status_value not in allowed_statuses:
            msg = f"unsupported stripe subscription status: {status_value}"
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        return status_value

    def _timestamp_to_datetime(self, value: object) -> datetime | None:
        if not isinstance(value, (int, float)):
            return None
        return datetime.fromtimestamp(value, UTC)

    def _require_user(self) -> StripeUserProtocol[str]:
        if self.current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
        if not isinstance(self.current_user, StripeUserProtocol):
            msg = "user model must expose stripe_customer_id"
            raise TypeError(msg)
        return self.current_user

    def _require_authenticated(self) -> tuple[StripeUserProtocol[str], SessionProtocol]:
        user = self._require_user()
        if self.current_session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
        return user, self.current_session
