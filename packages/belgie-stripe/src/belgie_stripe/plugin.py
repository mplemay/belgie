import inspect
import logging
import uuid
from typing import TYPE_CHECKING, Annotated

import stripe
from belgie_core.core.settings import BelgieSettings
from belgie_organization.plugin import OrganizationPlugin
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.organization import OrganizationAdapterProtocol
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
from belgie_stripe.settings import Stripe
from belgie_stripe.utils import maybe_await

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

type StripeBelgieClient = BelgieClientProtocol[StripeAccountProtocol, IndividualProtocol[str], SessionProtocol]
type StripeBelgieRuntime = BelgieRuntimeProtocol[StripeBelgieClient]


logger = logging.getLogger(__name__)


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
        self._organization_plugin: OrganizationPlugin | None = None
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

    def _resolve_organization_plugin(self, belgie: StripeBelgieRuntime) -> OrganizationPlugin | None:
        if self._organization_plugin_resolved:
            return self._organization_plugin

        self._organization_plugin_resolved = True
        self._organization_plugin = next(
            (plugin for plugin in belgie.plugins if isinstance(plugin, OrganizationPlugin)),
            None,
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
        ) -> StripeClient:
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

    async def after_update_individual(
        self,
        *,
        belgie: object,  # noqa: ARG002
        client: StripeBelgieClient,
        request: Request | None,  # noqa: ARG002
        previous_individual: IndividualProtocol[str],
        individual: IndividualProtocol[str],
    ) -> None:
        if previous_individual.email == individual.email:
            return
        if not isinstance(individual, StripeAccountProtocol) or individual.stripe_customer_id is None:
            return

        try:
            await self._build_client(
                belgie_client=client,
                current_individual=individual,
                current_session=None,
            ).sync_individual_email(
                previous_individual=previous_individual,
                individual=individual,
            )
        except stripe.error.StripeError:
            logger.exception(
                "failed to sync stripe customer email",
                extra={"stripe_customer_id": individual.stripe_customer_id},
            )

    def router(
        self,
        belgie: StripeBelgieRuntime,
    ) -> APIRouter:
        self._configure_organization_hooks(belgie)
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(tags=["auth", "stripe"])

        @router.post("/subscription/upgrade")
        async def upgrade_subscription(
            payload: UpgradeSubscriptionRequest,
            stripe: Annotated[StripeClient, Depends(self)],
        ) -> Response:
            result = await stripe.upgrade(data=payload)
            return _to_response(result)

        @router.get("/subscription/list")
        async def list_subscriptions(
            stripe: Annotated[StripeClient, Depends(self)],
            *,
            account_id: Annotated[uuid.UUID | None, Query()] = None,
            active_only: Annotated[bool, Query()] = False,
        ) -> list[SubscriptionView]:
            return await stripe.list_subscriptions(
                data=ListSubscriptionsRequest(account_id=account_id, active_only=active_only),
            )

        @router.post("/subscription/cancel")
        async def cancel_subscription(
            payload: CancelSubscriptionRequest,
            stripe: Annotated[StripeClient, Depends(self)],
        ) -> Response:
            result = await stripe.cancel(data=payload)
            return _to_response(result)

        @router.post("/subscription/restore")
        async def restore_subscription(
            payload: RestoreSubscriptionRequest,
            stripe: Annotated[StripeClient, Depends(self)],
        ) -> SubscriptionView:
            return await stripe.restore(data=payload)

        @router.post("/subscription/billing-portal")
        async def billing_portal(
            payload: BillingPortalRequest,
            stripe: Annotated[StripeClient, Depends(self)],
        ) -> Response:
            result = await stripe.create_billing_portal(data=payload)
            return _to_response(result)

        @router.get("/subscription/success")
        async def subscription_success(
            token: Annotated[str, Query(min_length=1)],
            client: Annotated[StripeBelgieClient, Depends(belgie)],
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
            client: Annotated[StripeBelgieClient, Depends(belgie)],
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
