import inspect
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.stripe import StripeAccountProtocol, StripeSubscriptionProtocol
from fastapi import APIRouter, Depends, Query, Request, Response, status
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

    from belgie_stripe.settings import Stripe

type StripeBelgieClient = BelgieClientProtocol[StripeAccountProtocol, IndividualProtocol[str], SessionProtocol]
type StripeBelgieRuntime = BelgieRuntimeProtocol[StripeBelgieClient]


class StripePlugin[
    SubscriptionT: StripeSubscriptionProtocol,
]:
    def __init__(
        self,
        belgie_settings: "BelgieSettings",
        settings: "Stripe[SubscriptionT]",
    ) -> None:
        self._belgie_settings = belgie_settings
        self._settings = settings
        self._resolve_client: Callable[..., Awaitable[StripeClient[SubscriptionT]]] | None = None

    @property
    def settings(self) -> "Stripe[SubscriptionT]":
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

        async def resolve_client(
            request: Request,
            client: Annotated[StripeBelgieClient, Depends(belgie)],
        ) -> StripeClient[SubscriptionT]:
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            return self._build_client(
                belgie_client=client,
                current_individual=individual,
                current_session=session,
            )

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
        if not self._settings.create_account_on_sign_up:
            return

        billing_client = self._build_client(
            belgie_client=client,
            current_individual=individual,
            current_session=None,
        )
        await billing_client.ensure_account(account_id=individual.id, metadata={})

    def router(
        self,
        belgie: StripeBelgieRuntime,
    ) -> APIRouter:
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(tags=["auth", "stripe"])
        stripe_dependency = Annotated[StripeClient, Depends(self)]
        belgie_dependency = Annotated[StripeBelgieClient, Depends(belgie)]

        @router.post("/subscription/upgrade")
        async def upgrade_subscription(
            payload: UpgradeSubscriptionRequest,
            stripe: stripe_dependency,
        ) -> Response:
            result = await stripe.upgrade(data=payload)
            return _to_response(result)

        @router.get("/subscription/list")
        async def list_subscriptions(
            stripe: stripe_dependency,
            account_id: Annotated[UUID | None, Query()] = None,
        ) -> list[SubscriptionView]:
            return await stripe.list_subscriptions(data=ListSubscriptionsRequest(account_id=account_id))

        @router.post("/subscription/cancel")
        async def cancel_subscription(
            payload: CancelSubscriptionRequest,
            stripe: stripe_dependency,
        ) -> Response:
            result = await stripe.cancel(data=payload)
            return _to_response(result)

        @router.post("/subscription/restore")
        async def restore_subscription(
            payload: RestoreSubscriptionRequest,
            stripe: stripe_dependency,
        ) -> SubscriptionView:
            return await stripe.restore(data=payload)

        @router.post("/subscription/billing-portal")
        async def billing_portal(
            payload: BillingPortalRequest,
            stripe: stripe_dependency,
        ) -> Response:
            result = await stripe.create_billing_portal(data=payload)
            return _to_response(result)

        @router.get("/subscription/success")
        async def subscription_success(
            token: Annotated[str, Query(min_length=1)],
            client: belgie_dependency,
        ) -> RedirectResponse:
            billing_client = self._build_client(belgie_client=client)
            return await billing_client.subscription_success(token=token)

        @router.post("/stripe/webhook")
        async def stripe_webhook(
            request: Request,
            client: belgie_dependency,
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
        return RedirectResponse(url=result.url, status_code=status.HTTP_302_FOUND)
    return JSONResponse(result.model_dump())
