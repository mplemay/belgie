from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import stripe
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.session import SessionProtocol
from belgie_proto.organization import OrganizationAdapterProtocol
from belgie_proto.stripe import (
    StripeAdapterProtocol,
    StripeBillingInterval,
    StripeCustomerType,
    StripeSubscriptionStatus,
    StripeUserProtocol,
)
from stripe import Customer, Event, ListObject, Price, Subscription
from stripe._billing_portal_service import BillingPortalService
from stripe._checkout_service import CheckoutService
from stripe._customer_service import CustomerService
from stripe._price_service import PriceService
from stripe._subscription_service import SubscriptionService
from stripe._v1_services import V1Services
from stripe.billing_portal import Session as BillingPortalSession
from stripe.billing_portal._session_service import SessionService as BillingPortalSessionService
from stripe.checkout import Session as CheckoutSession
from stripe.checkout._session_service import SessionService as CheckoutSessionService
from stripe.params import CustomerCreateParams, PriceListParams, SubscriptionUpdateParams, billing_portal, checkout

from belgie_stripe._protocols import (
    BelgieClientProtocol,
    BelgieRuntimeProtocol,
    StripeOrganizationAdapterProtocol,
    UserUpdateAdapterProtocol,
)

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.security import SecurityScopes
    from stripe._request_options import RequestOptions


@dataclass(slots=True)
class FakeUser:
    id: UUID
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str] = field(default_factory=list)
    stripe_customer_id: str | None = None


@dataclass(slots=True)
class FakeSession:
    id: UUID
    user_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class FakeOrganization:
    id: UUID
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime
    stripe_customer_id: str | None = None


@dataclass(slots=True)
class FakeMember:
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class FakeInvitation:
    id: UUID
    organization_id: UUID
    team_id: UUID | None
    email: str
    role: str
    status: str
    inviter_id: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class FakeSubscription:
    id: UUID
    plan: str
    reference_id: UUID
    customer_type: StripeCustomerType
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    status: StripeSubscriptionStatus
    period_start: datetime | None
    period_end: datetime | None
    cancel_at_period_end: bool
    cancel_at: datetime | None
    canceled_at: datetime | None
    ended_at: datetime | None
    billing_interval: StripeBillingInterval | None
    created_at: datetime
    updated_at: datetime


class FakeDB(DBConnection):
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeCoreAdapter(UserUpdateAdapterProtocol[StripeUserProtocol[str]]):
    def __init__(self, *, users: dict[UUID, FakeUser]) -> None:
        self.users = users

    async def update_user(
        self,
        session: DBConnection,
        user_id: UUID,
        **updates: str | None,
    ) -> FakeUser | None:
        assert session
        user = self.users.get(user_id)
        if user is None:
            return None
        for key, value in updates.items():
            if hasattr(user, key):
                setattr(user, key, value)
        user.updated_at = datetime.now(UTC)
        return user


class FakeBelgieClient(BelgieClientProtocol[StripeUserProtocol[str], SessionProtocol]):
    def __init__(self, *, user: FakeUser, session: FakeSession | None) -> None:
        self.user = user
        self.session = session
        self.db = FakeDB()
        self.adapter = FakeCoreAdapter(users={user.id: user})

    async def get_user(self, security_scopes: SecurityScopes, request: Request) -> FakeUser:
        assert security_scopes is not None
        assert request
        return self.user

    async def get_session(self, request: Request) -> FakeSession:
        assert request
        if self.session is None:
            msg = "missing session"
            raise RuntimeError(msg)
        return self.session


class DummyBelgie(BelgieRuntimeProtocol[BelgieClientProtocol[StripeUserProtocol[str], SessionProtocol]]):
    def __init__(self, client: FakeBelgieClient, *, plugins: list[object] | None = None) -> None:
        self._client = client
        self.plugins = [] if plugins is None else plugins
        self.__signature__ = inspect.Signature()

    def __call__(self, *_args: object, **_kwargs: object) -> FakeBelgieClient:
        return self._client


class FakeOrganizationAdapter(
    OrganizationAdapterProtocol[FakeOrganization, FakeMember, FakeInvitation],
    StripeOrganizationAdapterProtocol[FakeOrganization],
):
    def __init__(self, *, organizations: dict[UUID, FakeOrganization] | None = None) -> None:
        self.organizations = {} if organizations is None else organizations
        self.members: dict[UUID, FakeMember] = {}
        self.invitations: dict[UUID, FakeInvitation] = {}

    async def create_organization(
        self,
        session: DBConnection,
        *,
        name: str,
        slug: str,
        logo: str | None = None,
    ) -> FakeOrganization:
        assert session
        organization = FakeOrganization(
            id=uuid4(),
            name=name,
            slug=slug,
            logo=logo,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.organizations[organization.id] = organization
        return organization

    async def get_organization_by_id(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> FakeOrganization | None:
        assert session
        return self.organizations.get(organization_id)

    async def get_organization_by_slug(self, session: DBConnection, slug: str) -> FakeOrganization | None:
        assert session
        return next((organization for organization in self.organizations.values() if organization.slug == slug), None)

    async def update_organization(
        self,
        session: DBConnection,
        organization_id: UUID,
        *,
        name: str | None = None,
        slug: str | None = None,
        logo: str | None = None,
        stripe_customer_id: str | None = None,
    ) -> FakeOrganization | None:
        assert session
        organization = self.organizations.get(organization_id)
        if organization is None:
            return None
        if name is not None:
            organization.name = name
        if slug is not None:
            organization.slug = slug
        if logo is not None:
            organization.logo = logo
        if stripe_customer_id is not None:
            organization.stripe_customer_id = stripe_customer_id
        organization.updated_at = datetime.now(UTC)
        return organization

    async def delete_organization(self, session: DBConnection, organization_id: UUID) -> bool:
        assert session
        return self.organizations.pop(organization_id, None) is not None

    async def list_organizations_for_user(
        self,
        session: DBConnection,
        user_id: UUID,
    ) -> list[FakeOrganization]:
        assert session
        _ = user_id
        return list(self.organizations.values())

    async def create_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str,
    ) -> FakeMember:
        assert session
        now = datetime.now(UTC)
        member = FakeMember(
            id=uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            created_at=now,
            updated_at=now,
        )
        self.members[member.id] = member
        return member

    async def get_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> FakeMember | None:
        assert session
        return next(
            (
                member
                for member in self.members.values()
                if member.organization_id == organization_id and member.user_id == user_id
            ),
            None,
        )

    async def get_member_by_id(self, session: DBConnection, member_id: UUID) -> FakeMember | None:
        assert session
        return self.members.get(member_id)

    async def list_members(self, session: DBConnection, *, organization_id: UUID) -> list[FakeMember]:
        assert session
        return [member for member in self.members.values() if member.organization_id == organization_id]

    async def update_member_role(
        self,
        session: DBConnection,
        *,
        member_id: UUID,
        role: str,
    ) -> FakeMember | None:
        assert session
        member = self.members.get(member_id)
        if member is None:
            return None
        member.role = role
        member.updated_at = datetime.now(UTC)
        return member

    async def remove_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        assert session
        for member_id, member in list(self.members.items()):
            if member.organization_id == organization_id and member.user_id == user_id:
                del self.members[member_id]
                return True
        return False

    async def create_invitation(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        team_id: UUID | None,
        email: str,
        role: str,
        inviter_id: UUID,
        expires_at: datetime,
    ) -> FakeInvitation:
        assert session
        now = datetime.now(UTC)
        invitation = FakeInvitation(
            id=uuid4(),
            organization_id=organization_id,
            team_id=team_id,
            email=email,
            role=role,
            status="pending",
            inviter_id=inviter_id,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        self.invitations[invitation.id] = invitation
        return invitation

    async def get_invitation(self, session: DBConnection, invitation_id: UUID) -> FakeInvitation | None:
        assert session
        return self.invitations.get(invitation_id)

    async def get_pending_invitation(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        email: str,
    ) -> FakeInvitation | None:
        assert session
        return next(
            (
                invitation
                for invitation in self.invitations.values()
                if invitation.organization_id == organization_id
                and invitation.email == email
                and invitation.status == "pending"
            ),
            None,
        )

    async def list_invitations(self, session: DBConnection, *, organization_id: UUID) -> list[FakeInvitation]:
        assert session
        return [invitation for invitation in self.invitations.values() if invitation.organization_id == organization_id]

    async def list_user_invitations(self, session: DBConnection, *, email: str) -> list[FakeInvitation]:
        assert session
        return [invitation for invitation in self.invitations.values() if invitation.email == email]

    async def set_invitation_status(
        self,
        session: DBConnection,
        *,
        invitation_id: UUID,
        status: str,
    ) -> FakeInvitation | None:
        assert session
        invitation = self.invitations.get(invitation_id)
        if invitation is None:
            return None
        invitation.status = status
        invitation.updated_at = datetime.now(UTC)
        return invitation


class InMemoryStripeAdapter(StripeAdapterProtocol[FakeSubscription]):
    def __init__(self) -> None:
        self.subscriptions: dict[UUID, FakeSubscription] = {}
        self.subscription_by_id_responses: dict[UUID, list[FakeSubscription | None]] = {}

    async def create_subscription(
        self,
        session: DBConnection,
        *,
        plan: str,
        reference_id: UUID,
        customer_type: StripeCustomerType,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: StripeSubscriptionStatus = "incomplete",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        cancel_at_period_end: bool = False,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: StripeBillingInterval | None = None,
    ) -> FakeSubscription:
        assert session
        now = datetime.now(UTC)
        subscription = FakeSubscription(
            id=uuid4(),
            plan=plan,
            reference_id=reference_id,
            customer_type=customer_type,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status=status,
            period_start=period_start,
            period_end=period_end,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at,
            canceled_at=canceled_at,
            ended_at=ended_at,
            billing_interval=billing_interval,
            created_at=now,
            updated_at=now,
        )
        self.subscriptions[subscription.id] = subscription
        return subscription

    async def get_subscription_by_id(
        self,
        session: DBConnection,
        subscription_id: UUID,
    ) -> FakeSubscription | None:
        assert session
        if (queued_responses := self.subscription_by_id_responses.get(subscription_id)) and queued_responses:
            response = queued_responses.pop(0)
            if not queued_responses:
                del self.subscription_by_id_responses[subscription_id]
            return response
        return self.subscriptions.get(subscription_id)

    async def get_subscription_by_stripe_subscription_id(
        self,
        session: DBConnection,
        *,
        stripe_subscription_id: str,
    ) -> FakeSubscription | None:
        assert session
        return next(
            (
                subscription
                for subscription in self.subscriptions.values()
                if subscription.stripe_subscription_id == stripe_subscription_id
            ),
            None,
        )

    async def list_subscriptions(
        self,
        session: DBConnection,
        *,
        reference_id: UUID,
        customer_type: StripeCustomerType,
    ) -> list[FakeSubscription]:
        assert session
        subscriptions = [
            subscription
            for subscription in self.subscriptions.values()
            if subscription.reference_id == reference_id and subscription.customer_type == customer_type
        ]
        return sorted(subscriptions, key=lambda subscription: subscription.created_at, reverse=True)

    async def get_active_subscription(
        self,
        session: DBConnection,
        *,
        reference_id: UUID,
        customer_type: StripeCustomerType,
    ) -> FakeSubscription | None:
        for subscription in await self.list_subscriptions(
            session,
            reference_id=reference_id,
            customer_type=customer_type,
        ):
            if subscription.status in {"active", "past_due", "paused", "trialing", "unpaid"}:
                return subscription
        return None

    async def get_incomplete_subscription(
        self,
        session: DBConnection,
        *,
        reference_id: UUID,
        customer_type: StripeCustomerType,
    ) -> FakeSubscription | None:
        for subscription in await self.list_subscriptions(
            session,
            reference_id=reference_id,
            customer_type=customer_type,
        ):
            if subscription.status == "incomplete":
                return subscription
        return None

    async def update_subscription(
        self,
        session: DBConnection,
        *,
        subscription_id: UUID,
        plan: str | None = None,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: StripeSubscriptionStatus | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        cancel_at_period_end: bool | None = None,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: StripeBillingInterval | None = None,
    ) -> FakeSubscription | None:
        assert session
        subscription = self.subscriptions.get(subscription_id)
        if subscription is None:
            return None

        updated = replace(subscription)
        if plan is not None:
            updated.plan = plan
        if stripe_customer_id is not None:
            updated.stripe_customer_id = stripe_customer_id
        if stripe_subscription_id is not None:
            updated.stripe_subscription_id = stripe_subscription_id
        if status is not None:
            updated.status = status
        if period_start is not None:
            updated.period_start = period_start
        if period_end is not None:
            updated.period_end = period_end
        if cancel_at_period_end is not None:
            updated.cancel_at_period_end = cancel_at_period_end
        updated.cancel_at = cancel_at
        updated.canceled_at = canceled_at
        updated.ended_at = ended_at
        if billing_interval is not None:
            updated.billing_interval = billing_interval
        updated.updated_at = datetime.now(UTC)
        self.subscriptions[subscription_id] = updated
        return updated


class FakeCustomerService(CustomerService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self._sdk = sdk

    async def create_async(
        self,
        params: CustomerCreateParams | None = None,
        options: RequestOptions | None = None,
    ) -> Customer:
        assert options is None
        payload = CustomerCreateParams() if params is None else CustomerCreateParams(params)
        self._sdk.created_customers.append(payload)
        return Customer.construct_from(
            {"id": f"cus_{len(self._sdk.created_customers)}", "object": "customer"},
            key=None,
        )


class FakeCheckoutSessionService(CheckoutSessionService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self._sdk = sdk

    async def create_async(
        self,
        params: checkout.SessionCreateParams | None = None,
        options: RequestOptions | None = None,
    ) -> CheckoutSession:
        assert options is None
        payload = checkout.SessionCreateParams() if params is None else checkout.SessionCreateParams(params)
        self._sdk.created_checkout_sessions.append(payload)
        return CheckoutSession.construct_from(
            {
                "id": f"cs_{len(self._sdk.created_checkout_sessions)}",
                "object": "checkout.session",
                "url": "https://checkout.stripe.test/session",
            },
            key=None,
        )


class FakeCheckoutService(CheckoutService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self.sessions = FakeCheckoutSessionService(requestor, sdk)


class FakeBillingPortalSessionService(BillingPortalSessionService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self._sdk = sdk

    async def create_async(
        self,
        params: billing_portal.SessionCreateParams | None = None,
        options: RequestOptions | None = None,
    ) -> BillingPortalSession:
        assert options is None
        payload = billing_portal.SessionCreateParams() if params is None else billing_portal.SessionCreateParams(params)
        self._sdk.created_billing_portal_sessions.append(payload)
        return BillingPortalSession.construct_from(
            {
                "id": f"bps_{len(self._sdk.created_billing_portal_sessions)}",
                "object": "billing_portal.session",
                "url": "https://billing.stripe.test/session",
            },
            key=None,
        )


class FakeBillingPortalService(BillingPortalService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self.sessions = FakeBillingPortalSessionService(requestor, sdk)


class FakeSubscriptionService(SubscriptionService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self._sdk = sdk

    async def retrieve_async(
        self,
        subscription_exposed_id: str,
        params: object | None = None,
        options: RequestOptions | None = None,
    ) -> Subscription:
        assert params is None
        assert options is None
        return self._sdk.subscription_responses[subscription_exposed_id]

    async def update_async(
        self,
        subscription_exposed_id: str,
        params: SubscriptionUpdateParams | None = None,
        options: RequestOptions | None = None,
    ) -> Subscription:
        assert options is None
        payload = SubscriptionUpdateParams() if params is None else SubscriptionUpdateParams(params)
        self._sdk.modified_subscriptions.append((subscription_exposed_id, payload))
        subscription = self._sdk.subscription_responses[subscription_exposed_id]
        subscription.update(payload)
        return subscription


class FakePriceService(PriceService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self._sdk = sdk

    async def list_async(
        self,
        params: PriceListParams | None = None,
        options: RequestOptions | None = None,
    ) -> ListObject[Price]:
        assert options is None
        payload = PriceListParams() if params is None else PriceListParams(params)
        lookup_keys = payload.get("lookup_keys") or []
        return ListObject._construct_from(
            values={
                "object": "list",
                "data": [
                    {"id": price_id, "object": "price"}
                    for lookup_key in lookup_keys
                    if (price_id := self._sdk.price_lookup.get(lookup_key)) is not None
                ],
                "has_more": False,
                "url": "/v1/prices",
            },
            requestor=self._requestor,
            api_mode="V1",
        )


class FakeV1Services(V1Services):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self.customers = FakeCustomerService(requestor, sdk)
        self.checkout = FakeCheckoutService(requestor, sdk)
        self.billing_portal = FakeBillingPortalService(requestor, sdk)
        self.subscriptions = FakeSubscriptionService(requestor, sdk)
        self.prices = FakePriceService(requestor, sdk)


class FakeStripeSDK(stripe.StripeClient):
    def __init__(self) -> None:
        super().__init__("sk_test", http_client=stripe.HTTPXClient())

        self.created_customers: list[CustomerCreateParams] = []
        self.created_checkout_sessions: list[checkout.SessionCreateParams] = []
        self.created_billing_portal_sessions: list[billing_portal.SessionCreateParams] = []
        self.modified_subscriptions: list[tuple[str, SubscriptionUpdateParams]] = []
        self.subscription_responses: dict[str, Subscription] = {}
        self.price_lookup: dict[str, str] = {}
        self.event: Event | None = None
        self.construct_event_error: Exception | None = None
        self.construct_event_calls: list[tuple[bytes | str, str, str, int]] = []
        self.v1 = FakeV1Services(self._requestor, self)

    def construct_event(
        self,
        payload: bytes | str,
        sig_header: str,
        secret: str,
        tolerance: int = stripe.Webhook.DEFAULT_TOLERANCE,
    ) -> Event:
        assert payload
        assert sig_header
        assert secret
        assert tolerance == stripe.Webhook.DEFAULT_TOLERANCE
        self.construct_event_calls.append((payload, sig_header, secret, tolerance))
        if self.construct_event_error is not None:
            raise self.construct_event_error
        if self.event is None:
            msg = "event not configured"
            raise RuntimeError(msg)
        return self.event


def make_user(*, stripe_customer_id: str | None = None) -> FakeUser:
    now = datetime.now(UTC)
    return FakeUser(
        id=uuid4(),
        email="user@example.com",
        email_verified_at=now,
        name="Stripe User",
        image=None,
        created_at=now,
        updated_at=now,
        scopes=[],
        stripe_customer_id=stripe_customer_id,
    )


def make_session(*, user_id: UUID) -> FakeSession:
    now = datetime.now(UTC)
    return FakeSession(
        id=uuid4(),
        user_id=user_id,
        expires_at=now + timedelta(days=1),
        ip_address="127.0.0.1",
        user_agent="pytest",
        created_at=now,
        updated_at=now,
    )


def make_organization(
    *,
    organization_id: UUID | None = None,
    stripe_customer_id: str | None = None,
) -> FakeOrganization:
    now = datetime.now(UTC)
    return FakeOrganization(
        id=uuid4() if organization_id is None else organization_id,
        name="Acme",
        slug="acme",
        logo=None,
        created_at=now,
        updated_at=now,
        stripe_customer_id=stripe_customer_id,
    )


def make_stripe_subscription(
    *,
    subscription_id: str = "sub_123",
    customer_id: str = "cus_123",
    status: StripeSubscriptionStatus = "active",
    current_period_start: int | None = 1_710_000_000,
    current_period_end: int | None = 1_712_592_000,
    cancel_at_period_end: bool = False,
    cancel_at: int | None = None,
    canceled_at: int | None = None,
    ended_at: int | None = None,
    metadata: dict[str, str] | None = None,
    price_id: str = "price_pro",
    lookup_key: str | None = None,
    interval: StripeBillingInterval = "month",
    item_id: str = "si_123",
) -> Subscription:
    return Subscription.construct_from(
        {
            "id": subscription_id,
            "object": "subscription",
            "customer": customer_id,
            "status": status,
            "current_period_start": current_period_start,
            "current_period_end": current_period_end,
            "cancel_at_period_end": cancel_at_period_end,
            "cancel_at": cancel_at,
            "canceled_at": canceled_at,
            "ended_at": ended_at,
            "metadata": metadata or {},
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": item_id,
                        "object": "subscription_item",
                        "price": {
                            "id": price_id,
                            "object": "price",
                            "lookup_key": lookup_key,
                            "recurring": {"interval": interval},
                        },
                    },
                ],
                "has_more": False,
                "url": f"/v1/subscription_items?subscription={subscription_id}",
            },
        },
        key=None,
    )


def make_checkout_completed_event(
    *,
    subscription_id: str | None,
    metadata: dict[str, str] | None = None,
) -> Event:
    return Event.construct_from(
        {
            "id": "evt_1",
            "object": "event",
            "type": "checkout.session.completed",
            "created": 1_710_000_000,
            "livemode": False,
            "pending_webhooks": 0,
            "data": {
                "object": {
                    "id": "cs_123",
                    "object": "checkout.session",
                    "subscription": subscription_id,
                    "metadata": metadata or {},
                },
            },
        },
        key=None,
    )


def make_subscription_event(
    *,
    event_type: str,
    subscription: Subscription,
) -> Event:
    return Event.construct_from(
        {
            "id": "evt_1",
            "object": "event",
            "type": event_type,
            "created": 1_710_000_000,
            "livemode": False,
            "pending_webhooks": 0,
            "data": {"object": subscription.to_dict()},
        },
        key=None,
    )
