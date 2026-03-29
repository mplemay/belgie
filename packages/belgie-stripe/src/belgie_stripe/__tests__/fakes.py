from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import stripe


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
class FakeSubscription:
    id: UUID
    plan: str
    reference_id: UUID
    customer_type: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    status: str
    period_start: datetime | None
    period_end: datetime | None
    cancel_at_period_end: bool
    cancel_at: datetime | None
    canceled_at: datetime | None
    ended_at: datetime | None
    billing_interval: str | None
    created_at: datetime
    updated_at: datetime


class FakeCoreAdapter:
    def __init__(self, *, users: dict[UUID, FakeUser]) -> None:
        self.users = users

    async def update_user(self, _db: object, user_id: UUID, **updates: str | None) -> FakeUser | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        for key, value in updates.items():
            if hasattr(user, key):
                setattr(user, key, value)
        user.updated_at = datetime.now(UTC)
        return user


class FakeBelgieClient:
    def __init__(self, *, user: FakeUser, session: FakeSession | None) -> None:
        self.user = user
        self.session = session
        self.db = SimpleNamespace()
        self.adapter = FakeCoreAdapter(users={user.id: user})

    async def get_user(self, _security_scopes, _request) -> FakeUser:
        return self.user

    async def get_session(self, _request) -> FakeSession:
        if self.session is None:
            msg = "missing session"
            raise RuntimeError(msg)
        return self.session


class DummyBelgie:
    def __init__(self, client: FakeBelgieClient, *, plugins: list[object] | None = None) -> None:
        self._client = client
        self.plugins = [] if plugins is None else plugins

    async def __call__(self) -> FakeBelgieClient:
        return self._client


class FakeOrganizationAdapter:
    def __init__(self, *, organizations: dict[UUID, FakeOrganization] | None = None) -> None:
        self.organizations = {} if organizations is None else organizations

    async def create_organization(
        self,
        _db: object,
        *,
        name: str,
        slug: str,
        logo: str | None = None,
    ) -> FakeOrganization:
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

    async def get_organization_by_id(self, _db: object, organization_id: UUID) -> FakeOrganization | None:
        return self.organizations.get(organization_id)

    async def get_organization_by_slug(self, _db: object, slug: str) -> FakeOrganization | None:
        return next((organization for organization in self.organizations.values() if organization.slug == slug), None)

    async def update_organization(
        self,
        _db: object,
        organization_id: UUID,
        *,
        stripe_customer_id: str | None = None,
        **_updates: object,
    ) -> FakeOrganization | None:
        organization = self.organizations.get(organization_id)
        if organization is None:
            return None
        if stripe_customer_id is not None:
            organization.stripe_customer_id = stripe_customer_id
            organization.updated_at = datetime.now(UTC)
        return organization

    async def delete_organization(self, _db: object, organization_id: UUID) -> bool:
        return self.organizations.pop(organization_id, None) is not None

    async def list_organizations_for_user(self, _db: object, user_id: UUID) -> list[FakeOrganization]:  # noqa: ARG002
        return list(self.organizations.values())

    async def create_member(self, _db: object, **_kwargs: object) -> None:
        return None

    async def get_member(self, _db: object, **_kwargs: object) -> None:
        return None

    async def get_member_by_id(self, _db: object, member_id: UUID) -> None:  # noqa: ARG002
        return None

    async def list_members(self, _db: object, **_kwargs: object) -> list[object]:
        return []

    async def update_member_role(self, _db: object, **_kwargs: object) -> None:
        return None

    async def remove_member(self, _db: object, **_kwargs: object) -> bool:
        return False

    async def create_invitation(self, _db: object, **_kwargs: object) -> None:
        return None

    async def get_invitation(self, _db: object, invitation_id: UUID) -> None:  # noqa: ARG002
        return None

    async def get_pending_invitation(self, _db: object, **_kwargs: object) -> None:
        return None

    async def list_invitations(self, _db: object, **_kwargs: object) -> list[object]:
        return []

    async def list_user_invitations(self, _db: object, **_kwargs: object) -> list[object]:
        return []

    async def set_invitation_status(self, _db: object, **_kwargs: object) -> None:
        return None


class InMemoryStripeAdapter:
    def __init__(self) -> None:
        self.subscriptions: dict[UUID, FakeSubscription] = {}

    async def create_subscription(
        self,
        _db: object,
        *,
        plan: str,
        reference_id: UUID,
        customer_type: str,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: str = "incomplete",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        cancel_at_period_end: bool = False,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: str | None = None,
    ) -> FakeSubscription:
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

    async def get_subscription_by_id(self, _db: object, subscription_id: UUID) -> FakeSubscription | None:
        return self.subscriptions.get(subscription_id)

    async def get_subscription_by_stripe_subscription_id(
        self,
        _db: object,
        *,
        stripe_subscription_id: str,
    ) -> FakeSubscription | None:
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
        _db: object,
        *,
        reference_id: UUID,
        customer_type: str,
    ) -> list[FakeSubscription]:
        subscriptions = [
            subscription
            for subscription in self.subscriptions.values()
            if subscription.reference_id == reference_id and subscription.customer_type == customer_type
        ]
        return sorted(subscriptions, key=lambda subscription: subscription.created_at, reverse=True)

    async def get_active_subscription(
        self,
        _db: object,
        *,
        reference_id: UUID,
        customer_type: str,
    ) -> FakeSubscription | None:
        for subscription in await self.list_subscriptions(_db, reference_id=reference_id, customer_type=customer_type):
            if subscription.status in {"active", "past_due", "paused", "trialing", "unpaid"}:
                return subscription
        return None

    async def get_incomplete_subscription(
        self,
        _db: object,
        *,
        reference_id: UUID,
        customer_type: str,
    ) -> FakeSubscription | None:
        for subscription in await self.list_subscriptions(_db, reference_id=reference_id, customer_type=customer_type):
            if subscription.status == "incomplete":
                return subscription
        return None

    async def update_subscription(
        self,
        _db: object,
        *,
        subscription_id: UUID,
        plan: str | None = None,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: str | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        cancel_at_period_end: bool | None = None,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: str | None = None,
    ) -> FakeSubscription | None:
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


class FakeStripeSDK(stripe.StripeClient):
    def __init__(self) -> None:
        super().__init__("sk_test", http_client=stripe.HTTPXClient())

        self.created_customers: list[dict[str, object]] = []
        self.created_checkout_sessions: list[dict[str, object]] = []
        self.created_billing_portal_sessions: list[dict[str, object]] = []
        self.modified_subscriptions: list[tuple[str, dict[str, object]]] = []
        self.subscription_responses: dict[str, dict[str, object]] = {}
        self.price_lookup: dict[str, str] = {}
        self.event: dict[str, object] | None = None

        self.v1.customers.create_async = self._create_customer
        self.v1.checkout.sessions.create_async = self._create_checkout_session
        self.v1.billing_portal.sessions.create_async = self._create_billing_portal_session
        self.v1.subscriptions.retrieve_async = self._retrieve_subscription
        self.v1.subscriptions.update_async = self._update_subscription
        self.v1.prices.list_async = self._list_prices
        self.construct_event = self._construct_event

    async def _create_customer(self, params: object | None = None, _options: object | None = None) -> dict[str, str]:
        payload = dict(params or {})
        self.created_customers.append(payload)
        return {"id": f"cus_{len(self.created_customers)}"}

    async def _create_checkout_session(
        self,
        params: object | None = None,
        _options: object | None = None,
    ) -> dict[str, str]:
        payload = dict(params or {})
        self.created_checkout_sessions.append(payload)
        return {"url": "https://checkout.stripe.test/session"}

    async def _create_billing_portal_session(
        self,
        params: object | None = None,
        _options: object | None = None,
    ) -> dict[str, str]:
        payload = dict(params or {})
        self.created_billing_portal_sessions.append(payload)
        return {"url": "https://billing.stripe.test/session"}

    async def _retrieve_subscription(
        self,
        subscription_id: str,
        _params: object | None = None,
        _options: object | None = None,
    ) -> dict[str, object]:
        return self.subscription_responses[subscription_id]

    async def _update_subscription(
        self,
        subscription_id: str,
        params: object | None = None,
        _options: object | None = None,
    ) -> dict[str, object]:
        payload = dict(params or {})
        self.modified_subscriptions.append((subscription_id, payload))
        subscription = self.subscription_responses[subscription_id]
        subscription.update(payload)
        return subscription

    async def _list_prices(self, params: object | None = None, _options: object | None = None) -> dict[str, object]:
        lookup_keys: list[str] = []
        if isinstance(params, dict):
            lookup_keys = list(params.get("lookup_keys", []))
        return {
            "data": [
                {"id": price_id}
                for lookup_key in lookup_keys
                if (price_id := self.price_lookup.get(lookup_key)) is not None
            ],
        }

    def _construct_event(self, _payload: bytes, signature: str, secret: str) -> dict[str, object]:
        assert signature
        assert secret
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
