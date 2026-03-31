from __future__ import annotations

import inspect
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003

from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.stripe import StripeCustomerProtocol
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import SecurityScopes

from belgie_stripe._protocols import BelgieClientProtocol, BelgieRuntimeProtocol
from belgie_stripe.client import StripeClient
from belgie_stripe.models import (
    BillingPortalRequest,
    CancelSubscriptionRequest,
    ListSubscriptionsRequest,
    RestoreSubscriptionRequest,
    StripeRedirectResponse,
    SubscriptionView,
    UpgradeSubscriptionRequest,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.stripe import StripeSubscriptionProtocol

    from belgie_stripe.settings import Stripe

type StripeBelgieClient = BelgieClientProtocol[StripeCustomerProtocol, IndividualProtocol[str], SessionProtocol]
type StripeBelgieRuntime = BelgieRuntimeProtocol[StripeBelgieClient]


class StripePlugin[
    SubscriptionT: StripeSubscriptionProtocol,
]:
    def __init__(
        self,
        belgie_settings: BelgieSettings,
        settings: Stripe[SubscriptionT],
    ) -> None:
        self._belgie_settings = belgie_settings
        self._settings = settings
        self._resolve_client: Callable[..., Awaitable[StripeClient[SubscriptionT]]] | None = None

    @property
    def settings(self) -> Stripe[SubscriptionT]:
        return self._settings

    def _build_client(
        self,
        *,
        belgie_client: StripeBelgieClient,
        current_individual: IndividualProtocol[str] | None = None,
        current_session: SessionProtocol | None = None,
    ) -> StripeClient[SubscriptionT]:
        return StripeClient(
            client=belgie_client,
            belgie_settings=self._belgie_settings,
            settings=self._settings,
            current_individual=current_individual,
            current_session=current_session,
        )

    def _ensure_dependency_resolver(
        self,
        belgie: StripeBelgieRuntime,
    ) -> None:
        if self._resolve_client is not None:
            return

        belgie_dependency = Depends(belgie)

        async def resolve_client(
            request: Request,
            client: StripeBelgieClient = belgie_dependency,
        ) -> StripeClient[SubscriptionT]:
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            return self._build_client(
                belgie_client=client,
                current_individual=individual,
                current_session=session,
            )

        resolve_client.__annotations__["request"] = Request
        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    async def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> StripeClient[SubscriptionT]:
        if self._resolve_client is None:
            msg = (
                "StripePlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            )
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    async def after_sign_up(
        self,
        *,
        belgie: object,  # noqa: ARG002
        client: StripeBelgieClient,
        request: Request | None,  # noqa: ARG002
        individual: IndividualProtocol[str],
    ) -> None:
        if not self._settings.create_customer_on_sign_up:
            return

        billing_client = self._build_client(
            belgie_client=client,
            current_individual=individual,
            current_session=None,
        )
        await billing_client.ensure_customer(customer_id=individual.id, metadata={})

    def router(
        self,
        belgie: StripeBelgieRuntime,
    ) -> APIRouter:
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(tags=["auth", "stripe"])
        belgie_dependency = Depends(belgie)

        @router.post("/subscription/upgrade")
        async def upgrade_subscription(
            payload: UpgradeSubscriptionRequest,
            stripe: StripeClient = Depends(self),  # noqa: B008, FAST002
        ) -> Response:
            result = await stripe.upgrade(data=payload)
            return _to_response(result)

        @router.get("/subscription/list")
        async def list_subscriptions(
            stripe: StripeClient = Depends(self),  # noqa: B008, FAST002
            customer_id: UUID | None = None,
        ) -> list[SubscriptionView]:
            return await stripe.list_subscriptions(data=ListSubscriptionsRequest(customer_id=customer_id))

        @router.post("/subscription/cancel")
        async def cancel_subscription(
            payload: CancelSubscriptionRequest,
            stripe: StripeClient = Depends(self),  # noqa: B008, FAST002
        ) -> Response:
            result = await stripe.cancel(data=payload)
            return _to_response(result)

        @router.post("/subscription/restore")
        async def restore_subscription(
            payload: RestoreSubscriptionRequest,
            stripe: StripeClient = Depends(self),  # noqa: B008, FAST002
        ) -> SubscriptionView:
            return await stripe.restore(data=payload)

        @router.post("/subscription/billing-portal")
        async def billing_portal(
            payload: BillingPortalRequest,
            stripe: StripeClient = Depends(self),  # noqa: B008, FAST002
        ) -> Response:
            result = await stripe.create_billing_portal(data=payload)
            return _to_response(result)

        @router.get("/subscription/success")
        async def subscription_success(
            token: str,
            client: StripeBelgieClient = belgie_dependency,
        ) -> RedirectResponse:
            billing_client = self._build_client(belgie_client=client)
            return await billing_client.subscription_success(token=token)

        @router.post("/stripe/webhook")
        async def stripe_webhook(
            request: Request,
            client: StripeBelgieClient = belgie_dependency,
        ) -> dict[str, bool]:
            billing_client = self._build_client(belgie_client=client)
            return await billing_client.handle_webhook(request=request)

        return router

    def public(
        self,
        _belgie: StripeBelgieRuntime,
    ) -> APIRouter | None:
        return None


def _to_response(result: StripeRedirectResponse) -> Response:
    if result.redirect:
        return RedirectResponse(url=result.url, status_code=302)
    return JSONResponse(result.model_dump())
