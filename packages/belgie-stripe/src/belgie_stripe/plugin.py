from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Literal
from uuid import UUID  # noqa: TC003

from belgie_core.core.client import BelgieClient  # noqa: TC002
from belgie_core.core.plugin import AfterSignUpHook, PluginClient
from belgie_organization.plugin import OrganizationPlugin
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import SecurityScopes

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

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.organization import (
        InvitationProtocol,
        MemberProtocol,
        OrganizationAdapterProtocol,
        OrganizationProtocol,
    )
    from belgie_proto.stripe import StripeSubscriptionProtocol, StripeUserProtocol

    from belgie_stripe.settings import Stripe


class StripePlugin[
    SubscriptionT: StripeSubscriptionProtocol,
](PluginClient, AfterSignUpHook):
    def __init__(
        self,
        belgie_settings: BelgieSettings,
        settings: Stripe[SubscriptionT],
    ) -> None:
        self._belgie_settings = belgie_settings
        self._settings = settings
        self._resolve_client: Callable[..., Awaitable[StripeClient[SubscriptionT]]] | None = None
        self._organization_adapter: (
            OrganizationAdapterProtocol[OrganizationProtocol, MemberProtocol, InvitationProtocol] | None
        ) = None

    @property
    def settings(self) -> Stripe[SubscriptionT]:
        return self._settings

    def _ensure_organization_adapter(self, belgie: Belgie) -> None:
        if not self._settings.organization or not self._settings.organization.enabled:
            return
        if self._organization_adapter is not None:
            return

        organization_plugin = next(
            (plugin for plugin in belgie.plugins if isinstance(plugin, OrganizationPlugin)),
            None,
        )
        if organization_plugin is None:
            msg = "stripe plugin requires organization plugin when organization billing is enabled"
            raise RuntimeError(msg)
        self._organization_adapter = organization_plugin.settings.adapter

    def _build_client(
        self,
        *,
        belgie_client: BelgieClient,
        current_user: StripeUserProtocol[str] | None = None,
        current_session: object | None = None,
    ) -> StripeClient[SubscriptionT]:
        return StripeClient(
            client=belgie_client,
            belgie_settings=self._belgie_settings,
            settings=self._settings,
            current_user=current_user,
            current_session=current_session,
            organization_adapter=self._organization_adapter,
        )

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return
        self._ensure_organization_adapter(belgie)

        async def resolve_client(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> StripeClient[SubscriptionT]:
            user = await client.get_user(SecurityScopes(), request)
            session = await client.get_session(request)
            return self._build_client(
                belgie_client=client,
                current_user=user,
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
        belgie: Belgie,  # noqa: ARG002
        client: BelgieClient,
        request: Request | None,  # noqa: ARG002
        user: StripeUserProtocol[str],
    ) -> None:
        if not self._settings.create_customer_on_sign_up:
            return
        billing_client = self._build_client(
            belgie_client=client,
            current_user=user,
            current_session=None,
        )
        await billing_client.ensure_user_customer(metadata={})

    def router(self, belgie: Belgie) -> APIRouter:
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(tags=["auth", "stripe"])

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
            reference_id: UUID | None = None,
            customer_type: Literal["user", "organization"] = "user",
        ) -> list[SubscriptionView]:
            query = ListSubscriptionsRequest(
                reference_id=reference_id,
                customer_type=customer_type,
            )
            return await stripe.list_subscriptions(data=query)

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
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            billing_client = self._build_client(belgie_client=client)
            return await billing_client.subscription_success(token=token)

        @router.post("/stripe/webhook")
        async def stripe_webhook(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> dict[str, bool]:
            billing_client = self._build_client(belgie_client=client)
            return await billing_client.handle_webhook(request=request)

        return router

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None


def _to_response(result: StripeRedirectResponse) -> Response:
    if result.redirect:
        return RedirectResponse(url=result.url, status_code=302)
    return JSONResponse(result.model_dump())
