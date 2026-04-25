from __future__ import annotations

import importlib
import inspect
from typing import TYPE_CHECKING, Annotated

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
from belgie_stripe.utils import maybe_await

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.organization import OrganizationAdapterProtocol

    from belgie_stripe.settings import Stripe

type StripeBelgieClient = BelgieClientProtocol[StripeAccountProtocol, IndividualProtocol[str], SessionProtocol]
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
        self._organization_plugin = None
        self._organization_plugin_resolved = False
        self._organization_hooks_configured = False

    @property
    def settings(self) -> Stripe[SubscriptionT]:
        return self._settings

    def _build_client(
        self,
        *,
        belgie_client: StripeBelgieClient,
        current_individual: IndividualProtocol[str] | None = None,
        current_session: SessionProtocol | None = None,
        organization_adapter: OrganizationAdapterProtocol | None = None,
    ) -> StripeClient[SubscriptionT]:
        return StripeClient(
            client=belgie_client,
            belgie_settings=self._belgie_settings,
            settings=self._settings,
            current_individual=current_individual,
            current_session=current_session,
            organization_adapter=organization_adapter,
        )

    def _resolve_organization_plugin(self, belgie: StripeBelgieRuntime) -> object | None:
        if self._organization_plugin_resolved:
            return self._organization_plugin

        self._organization_plugin_resolved = True
        try:
            organization_plugin_type = importlib.import_module("belgie_organization.plugin").OrganizationPlugin
        except ModuleNotFoundError:
            organization_plugin_type = None
        self._organization_plugin = (
            None
            if organization_plugin_type is None
            else next(
                (plugin for plugin in belgie.plugins if isinstance(plugin, organization_plugin_type)),
                None,
            )
        )
        return self._organization_plugin

    def _organization_adapter(
        self,
        belgie: StripeBelgieRuntime,
    ) -> OrganizationAdapterProtocol | None:
        organization_plugin = self._resolve_organization_plugin(belgie)
        if organization_plugin is None:
            return None
        return organization_plugin.settings.adapter

    def _configure_organization_hooks(self, belgie: StripeBelgieRuntime) -> None:  # noqa: C901
        if self._organization_hooks_configured:
            return
        self._organization_hooks_configured = True
        organization_plugin = self._resolve_organization_plugin(belgie)
        if organization_plugin is None:
            return

        existing_after_update = organization_plugin.settings.after_update
        existing_before_delete = organization_plugin.settings.before_delete
        existing_after_member_add = organization_plugin.settings.after_member_add
        existing_after_member_remove = organization_plugin.settings.after_member_remove
        existing_after_invitation_accept = organization_plugin.settings.after_invitation_accept
        organization_adapter = organization_plugin.settings.adapter

        async def after_update(organization_client, organization) -> None:  # noqa: ANN001
            if existing_after_update is not None:
                await maybe_await(existing_after_update(organization_client, organization))
            await self._build_client(
                belgie_client=organization_client.client,
                organization_adapter=organization_adapter,
            ).sync_organization_name(organization_id=organization.id)

        async def before_delete(organization_client, organization) -> None:  # noqa: ANN001
            if existing_before_delete is not None:
                await maybe_await(existing_before_delete(organization_client, organization))
            await self._build_client(
                belgie_client=organization_client.client,
                organization_adapter=organization_adapter,
            ).ensure_organization_can_delete(organization_id=organization.id)

        async def after_member_add(organization_client, organization, member) -> None:  # noqa: ANN001
            if existing_after_member_add is not None:
                await maybe_await(existing_after_member_add(organization_client, organization, member))
            await self._build_client(
                belgie_client=organization_client.client,
                organization_adapter=organization_adapter,
            ).sync_organization_seats(organization_id=organization.id)

        async def after_member_remove(organization_client, organization, member) -> None:  # noqa: ANN001
            if existing_after_member_remove is not None:
                await maybe_await(existing_after_member_remove(organization_client, organization, member))
            await self._build_client(
                belgie_client=organization_client.client,
                organization_adapter=organization_adapter,
            ).sync_organization_seats(organization_id=organization.id)

        async def after_invitation_accept(organization_client, organization, invitation, member) -> None:  # noqa: ANN001
            if existing_after_invitation_accept is not None:
                await maybe_await(
                    existing_after_invitation_accept(
                        organization_client,
                        organization,
                        invitation,
                        member,
                    ),
                )
            await self._build_client(
                belgie_client=organization_client.client,
                organization_adapter=organization_adapter,
            ).sync_organization_seats(organization_id=organization.id)

        organization_plugin.settings.after_update = after_update
        organization_plugin.settings.before_delete = before_delete
        organization_plugin.settings.after_member_add = after_member_add
        organization_plugin.settings.after_member_remove = after_member_remove
        organization_plugin.settings.after_invitation_accept = after_invitation_accept

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
                organization_adapter=self._organization_adapter(belgie),
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
        self._configure_organization_hooks(belgie)
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(tags=["auth", "stripe"])
        type StripeDep = Annotated[StripeClient, Depends(self)]
        type BelgieDep = Annotated[StripeBelgieClient, Depends(belgie)]

        @router.post("/subscription/upgrade")
        async def upgrade_subscription(
            payload: UpgradeSubscriptionRequest,
            stripe: StripeDep,
        ) -> Response:
            result = await stripe.upgrade(data=payload)
            return _to_response(result)

        @router.get("/subscription/list")
        async def list_subscriptions(
            stripe: StripeDep,
            account_id: Annotated[UUID | None, Query(default=None)],
            active_only: Annotated[bool, Query(default=False)],
        ) -> list[SubscriptionView]:
            return await stripe.list_subscriptions(
                data=ListSubscriptionsRequest(account_id=account_id, active_only=active_only),
            )

        @router.post("/subscription/cancel")
        async def cancel_subscription(
            payload: CancelSubscriptionRequest,
            stripe: StripeDep,
        ) -> Response:
            result = await stripe.cancel(data=payload)
            return _to_response(result)

        @router.post("/subscription/restore")
        async def restore_subscription(
            payload: RestoreSubscriptionRequest,
            stripe: StripeDep,
        ) -> SubscriptionView:
            return await stripe.restore(data=payload)

        @router.post("/subscription/billing-portal")
        async def billing_portal(
            payload: BillingPortalRequest,
            stripe: StripeDep,
        ) -> Response:
            result = await stripe.create_billing_portal(data=payload)
            return _to_response(result)

        @router.get("/subscription/success")
        async def subscription_success(
            token: Annotated[str, Query(min_length=1)],
            client: BelgieDep,
            checkout_session_id: Annotated[str | None, Query()] = None,
        ) -> RedirectResponse:
            billing_client = self._build_client(belgie_client=client)
            return await billing_client.subscription_success(
                token=token,
                checkout_session_id=checkout_session_id,
            )

        @router.post("/stripe/webhook")
        async def stripe_webhook(
            request: Request,
            client: BelgieDep,
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
