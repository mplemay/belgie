from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import stripe
import stripe._customer as _stripe_customer
from belgie_proto.core.account import AccountType
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.session import SessionProtocol
from belgie_proto.stripe import (
    UNSET,
    StripeAdapterProtocol,
    StripeBillingInterval,
    StripeSubscriptionStatus,
    StripeUnset,
)
from stripe import Event, ListObject, Price, Subscription
from stripe._billing_portal_service import BillingPortalService
from stripe._checkout_service import CheckoutService
from stripe._customer_service import CustomerService
from stripe._price_service import PriceService
from stripe._stripe_object import StripeObject
from stripe._subscription_schedule import SubscriptionSchedule
from stripe._subscription_schedule_service import SubscriptionScheduleService
from stripe._subscription_service import SubscriptionService
from stripe._v1_services import V1Services
from stripe.billing_portal import Session as BillingPortalSession
from stripe.billing_portal._session_service import SessionService as BillingPortalSessionService
from stripe.checkout import Session as CheckoutSession
from stripe.checkout._session_service import SessionService as CheckoutSessionService
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

from belgie_stripe._protocols import BelgieClientProtocol, BelgieRuntimeProtocol, StripeCoreAdapterProtocol

# Stripe 15.0.x exposes Customer; later 15.x renamed the class to Account on the same module.
Customer = getattr(_stripe_customer, "Account", None) or _stripe_customer.Customer

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.security import SecurityScopes
    from stripe._request_options import RequestOptions
    from stripe.params._subscription_update_params import SubscriptionUpdateParamsItem


@dataclass(slots=True, kw_only=True)
class FakeIndividual:
    id: UUID
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    account_type: AccountType = AccountType.INDIVIDUAL
    scopes: list[str] = field(default_factory=list)
    stripe_customer_id: str | None = None


@dataclass(slots=True, kw_only=True)
class FakeOrganization:
    id: UUID
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime
    account_type: AccountType = AccountType.ORGANIZATION
    stripe_customer_id: str | None = None


@dataclass(slots=True, kw_only=True)
class FakeTeam:
    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    account_type: AccountType = AccountType.TEAM
    stripe_customer_id: str | None = None


type FakeAccount = FakeIndividual | FakeOrganization | FakeTeam


@dataclass(slots=True, kw_only=True)
class FakeSession:
    id: UUID
    individual_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, kw_only=True)
class FakeSubscription:
    id: UUID
    plan: str
    account_id: UUID
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    status: StripeSubscriptionStatus
    period_start: datetime | None
    period_end: datetime | None
    trial_start: datetime | None
    trial_end: datetime | None
    seats: int | None
    cancel_at_period_end: bool
    cancel_at: datetime | None
    canceled_at: datetime | None
    ended_at: datetime | None
    billing_interval: StripeBillingInterval | None
    stripe_schedule_id: str | None
    created_at: datetime
    updated_at: datetime


class FakeDB(DBConnection):
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeCoreAdapter(StripeCoreAdapterProtocol[FakeAccount]):
    def __init__(self, *, accounts: dict[UUID, FakeAccount]) -> None:
        self.accounts = accounts

    async def get_account_by_id(
        self,
        session: DBConnection,
        account_id: UUID,
    ) -> FakeAccount | None:
        assert session
        return self.accounts.get(account_id)

    async def update_account(
        self,
        session: DBConnection,
        account_id: UUID,
        **updates: str | None,
    ) -> FakeAccount | None:
        assert session
        account = self.accounts.get(account_id)
        if account is None:
            return None
        for key, value in updates.items():
            if hasattr(account, key):
                setattr(account, key, value)
        account.updated_at = datetime.now(UTC)
        return account


class FakeBelgieClient(BelgieClientProtocol[FakeAccount, FakeIndividual, FakeSession]):
    def __init__(
        self,
        *,
        individual: FakeIndividual,
        accounts: dict[UUID, FakeAccount] | None = None,
        session: FakeSession | None,
    ) -> None:
        self.individual = individual
        self.session = session
        self.db = FakeDB()
        self.accounts = {individual.id: individual, **({} if accounts is None else accounts)}
        self.adapter = FakeCoreAdapter(accounts=self.accounts)

    async def get_individual(
        self,
        security_scopes: SecurityScopes,
        request: Request,
    ) -> FakeIndividual:
        assert security_scopes is not None
        assert request
        return self.individual

    async def get_session(self, request: Request) -> FakeSession:
        assert request
        if self.session is None:
            msg = "missing session"
            raise RuntimeError(msg)
        return self.session


class DummyBelgie(BelgieRuntimeProtocol[BelgieClientProtocol[FakeAccount, FakeIndividual, SessionProtocol]]):
    def __init__(self, client: FakeBelgieClient, *, plugins: list[object] | None = None) -> None:
        self._client = client
        self.plugins = [] if plugins is None else plugins
        self.__signature__ = inspect.Signature()

    def __call__(self, *_args: object, **_kwargs: object) -> FakeBelgieClient:
        return self._client


class InMemoryStripeAdapter(StripeAdapterProtocol[FakeSubscription]):
    def __init__(self) -> None:
        self.subscriptions: dict[UUID, FakeSubscription] = {}
        self.subscription_by_id_responses: dict[UUID, list[FakeSubscription | None]] = {}

    async def create_subscription(
        self,
        session: DBConnection,
        *,
        plan: str,
        account_id: UUID,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: StripeSubscriptionStatus = "incomplete",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        trial_start: datetime | None = None,
        trial_end: datetime | None = None,
        seats: int | None = None,
        cancel_at_period_end: bool = False,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: StripeBillingInterval | None = None,
        stripe_schedule_id: str | None = None,
    ) -> FakeSubscription:
        assert session
        now = datetime.now(UTC)
        subscription = FakeSubscription(
            id=uuid4(),
            plan=plan,
            account_id=account_id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status=status,
            period_start=period_start,
            period_end=period_end,
            trial_start=trial_start,
            trial_end=trial_end,
            seats=seats,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at,
            canceled_at=canceled_at,
            ended_at=ended_at,
            billing_interval=billing_interval,
            stripe_schedule_id=stripe_schedule_id,
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
        account_id: UUID,
        active_only: bool = False,
    ) -> list[FakeSubscription]:
        assert session
        subscriptions = [
            subscription for subscription in self.subscriptions.values() if subscription.account_id == account_id
        ]
        if active_only:
            subscriptions = [
                subscription
                for subscription in subscriptions
                if subscription.status in {"active", "past_due", "paused", "trialing", "unpaid"}
            ]
        return sorted(subscriptions, key=lambda subscription: subscription.created_at, reverse=True)

    async def get_active_subscription(
        self,
        session: DBConnection,
        *,
        account_id: UUID,
    ) -> FakeSubscription | None:
        for subscription in await self.list_subscriptions(session, account_id=account_id):
            if subscription.status in {"active", "past_due", "paused", "trialing", "unpaid"}:
                return subscription
        return None

    async def get_incomplete_subscription(
        self,
        session: DBConnection,
        *,
        account_id: UUID,
    ) -> FakeSubscription | None:
        for subscription in await self.list_subscriptions(session, account_id=account_id):
            if subscription.status == "incomplete":
                return subscription
        return None

    async def update_subscription(  # noqa: C901, PLR0912
        self,
        session: DBConnection,
        *,
        subscription_id: UUID,
        plan: str | StripeUnset = UNSET,
        stripe_customer_id: str | None | StripeUnset = UNSET,
        stripe_subscription_id: str | None | StripeUnset = UNSET,
        status: StripeSubscriptionStatus | StripeUnset = UNSET,
        period_start: datetime | None | StripeUnset = UNSET,
        period_end: datetime | None | StripeUnset = UNSET,
        trial_start: datetime | None | StripeUnset = UNSET,
        trial_end: datetime | None | StripeUnset = UNSET,
        seats: int | None | StripeUnset = UNSET,
        cancel_at_period_end: bool | StripeUnset = UNSET,
        cancel_at: datetime | None | StripeUnset = UNSET,
        canceled_at: datetime | None | StripeUnset = UNSET,
        ended_at: datetime | None | StripeUnset = UNSET,
        billing_interval: StripeBillingInterval | None | StripeUnset = UNSET,
        stripe_schedule_id: str | None | StripeUnset = UNSET,
    ) -> FakeSubscription | None:
        assert session
        subscription = self.subscriptions.get(subscription_id)
        if subscription is None:
            return None

        updated = replace(subscription)
        if not isinstance(plan, StripeUnset):
            updated.plan = plan
        if not isinstance(stripe_customer_id, StripeUnset):
            updated.stripe_customer_id = stripe_customer_id
        if not isinstance(stripe_subscription_id, StripeUnset):
            updated.stripe_subscription_id = stripe_subscription_id
        if not isinstance(status, StripeUnset):
            updated.status = status
        if not isinstance(period_start, StripeUnset):
            updated.period_start = period_start
        if not isinstance(period_end, StripeUnset):
            updated.period_end = period_end
        if not isinstance(trial_start, StripeUnset):
            updated.trial_start = trial_start
        if not isinstance(trial_end, StripeUnset):
            updated.trial_end = trial_end
        if not isinstance(seats, StripeUnset):
            updated.seats = seats
        if not isinstance(cancel_at_period_end, StripeUnset):
            updated.cancel_at_period_end = cancel_at_period_end
        if not isinstance(cancel_at, StripeUnset):
            updated.cancel_at = cancel_at
        if not isinstance(canceled_at, StripeUnset):
            updated.canceled_at = canceled_at
        if not isinstance(ended_at, StripeUnset):
            updated.ended_at = ended_at
        if not isinstance(billing_interval, StripeUnset):
            updated.billing_interval = billing_interval
        if not isinstance(stripe_schedule_id, StripeUnset):
            updated.stripe_schedule_id = stripe_schedule_id
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
        customer = Customer.construct_from(
            {
                "id": f"cus_{len(self._sdk.created_customers)}",
                "object": "customer",
                "email": payload.get("email"),
                "name": payload.get("name"),
                "metadata": payload.get("metadata") or {},
            },
            key=None,
        )
        self._sdk.customer_responses[customer.id] = customer
        return customer

    async def search_async(
        self,
        params: CustomerSearchParams,
        options: RequestOptions | None = None,
    ) -> ListObject[Customer]:
        assert options is None
        self._sdk.searched_customers.append(params)
        query = params.get("query", "")
        email = _extract_search_email(query)
        account_id = _extract_search_metadata(query, "account_id")
        account_type = _extract_search_metadata(query, "account_type")
        customers = list(self._sdk.customer_responses.values())
        if email is not None:
            customers = [customer for customer in customers if customer.email == email]
        if account_id is not None:
            customers = [
                customer for customer in customers if _metadata_dict(customer.metadata).get("account_id") == account_id
            ]
        if account_type is not None:
            customers = [
                customer
                for customer in customers
                if _metadata_dict(customer.metadata).get("account_type") == account_type
            ]
        return _list_object(customers)

    async def list_async(
        self,
        params: CustomerListParams | None = None,
        options: RequestOptions | None = None,
    ) -> ListObject[Customer]:
        assert options is None
        payload = CustomerListParams() if params is None else CustomerListParams(params)
        self._sdk.listed_customers.append(payload)
        email = payload.get("email")
        customers = list(self._sdk.customer_responses.values())
        if email is not None:
            customers = [customer for customer in customers if customer.email == email]
        return _list_object(customers)

    async def update_async(
        self,
        customer: str,
        params: CustomerUpdateParams | None = None,
        options: RequestOptions | None = None,
    ) -> Customer:
        assert options is None
        payload = CustomerUpdateParams() if params is None else CustomerUpdateParams(params)
        self._sdk.updated_customers.append((customer, payload))
        existing = self._sdk.customer_responses.get(customer)
        if existing is None:
            existing = Customer.construct_from({"id": customer, "object": "customer"}, key=None)
            self._sdk.customer_responses[customer] = existing
        existing.update(payload)
        return existing


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
        session = CheckoutSession.construct_from(
            {
                "id": f"cs_{len(self._sdk.created_checkout_sessions)}",
                "object": "checkout.session",
                "url": "https://checkout.stripe.test/session",
                "metadata": payload.get("metadata") or {},
                "subscription": None,
            },
            key=None,
        )
        self._sdk.checkout_session_responses[session.id] = session
        return session

    async def retrieve_async(
        self,
        session: str,
        params: object | None = None,
        options: RequestOptions | None = None,
    ) -> CheckoutSession:
        assert params is None
        assert options is None
        return self._sdk.checkout_session_responses[session]


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
        subscription.update({key: value for key, value in payload.items() if key != "items"})
        if (items := payload.get("items")) is not None:
            _apply_subscription_items_update(
                subscription=subscription,
                items=items,
                sdk=self._sdk,
            )
        return subscription


class FakeSubscriptionScheduleService(SubscriptionScheduleService):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self._sdk = sdk

    async def create_async(
        self,
        params: SubscriptionScheduleCreateParams | None = None,
        options: RequestOptions | None = None,
    ) -> SubscriptionSchedule:
        assert options is None
        payload = SubscriptionScheduleCreateParams() if params is None else SubscriptionScheduleCreateParams(params)
        self._sdk.created_subscription_schedules.append(payload)
        schedule = SubscriptionSchedule.construct_from(
            {
                "id": f"sub_sched_{len(self._sdk.created_subscription_schedules)}",
                "object": "subscription_schedule",
                "metadata": payload.get("metadata") or {},
                "status": "active",
                "subscription": payload.get("from_subscription"),
            },
            key=None,
        )
        self._sdk.subscription_schedule_responses[schedule.id] = schedule
        return schedule

    async def update_async(
        self,
        schedule: str,
        params: SubscriptionScheduleUpdateParams | None = None,
        options: RequestOptions | None = None,
    ) -> SubscriptionSchedule:
        assert options is None
        payload = SubscriptionScheduleUpdateParams() if params is None else SubscriptionScheduleUpdateParams(params)
        self._sdk.updated_subscription_schedules.append((schedule, payload))
        existing = self._sdk.subscription_schedule_responses[schedule]
        existing.update(payload)
        return existing

    async def release_async(
        self,
        schedule: str,
        params: SubscriptionScheduleReleaseParams | None = None,
        options: RequestOptions | None = None,
    ) -> SubscriptionSchedule:
        assert options is None
        payload = SubscriptionScheduleReleaseParams() if params is None else SubscriptionScheduleReleaseParams(params)
        self._sdk.released_subscription_schedules.append((schedule, payload))
        existing = self._sdk.subscription_schedule_responses.get(schedule)
        if existing is None:
            existing = SubscriptionSchedule.construct_from(
                {"id": schedule, "object": "subscription_schedule", "status": "released"},
                key=None,
            )
            self._sdk.subscription_schedule_responses[schedule] = existing
        existing["status"] = "released"
        return existing


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

    async def retrieve_async(
        self,
        price: str,
        params: object | None = None,
        options: RequestOptions | None = None,
    ) -> Price:
        assert params is None
        assert options is None
        if price not in self._sdk.price_responses:
            self._sdk.price_responses[price] = make_price(price_id=price)
        return self._sdk.price_responses[price]


class FakeV1Services(V1Services):
    def __init__(self, requestor: object, sdk: FakeStripeSDK) -> None:
        super().__init__(requestor)
        self.customers = FakeCustomerService(requestor, sdk)
        self.checkout = FakeCheckoutService(requestor, sdk)
        self.billing_portal = FakeBillingPortalService(requestor, sdk)
        self.subscriptions = FakeSubscriptionService(requestor, sdk)
        self.subscription_schedules = FakeSubscriptionScheduleService(requestor, sdk)
        self.prices = FakePriceService(requestor, sdk)


class FakeStripeSDK(stripe.StripeClient):
    def __init__(self) -> None:
        super().__init__("sk_test", http_client=stripe.HTTPXClient())

        self.created_customers: list[CustomerCreateParams] = []
        self.searched_customers: list[CustomerSearchParams] = []
        self.listed_customers: list[CustomerListParams] = []
        self.updated_customers: list[tuple[str, CustomerUpdateParams]] = []
        self.customer_responses: dict[str, Customer] = {}
        self.created_checkout_sessions: list[checkout.SessionCreateParams] = []
        self.checkout_session_responses: dict[str, CheckoutSession] = {}
        self.created_billing_portal_sessions: list[billing_portal.SessionCreateParams] = []
        self.modified_subscriptions: list[tuple[str, SubscriptionUpdateParams]] = []
        self.created_subscription_schedules: list[SubscriptionScheduleCreateParams] = []
        self.updated_subscription_schedules: list[tuple[str, SubscriptionScheduleUpdateParams]] = []
        self.released_subscription_schedules: list[tuple[str, SubscriptionScheduleReleaseParams]] = []
        self.subscription_schedule_responses: dict[str, SubscriptionSchedule] = {}
        self.subscription_responses: dict[str, Subscription] = {}
        self.price_lookup: dict[str, str] = {}
        self.price_responses: dict[str, Price] = {}
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


def make_individual(*, stripe_customer_id: str | None = None) -> FakeIndividual:
    now = datetime.now(UTC)
    return FakeIndividual(
        id=uuid4(),
        email="individual@example.com",
        email_verified_at=now,
        name="Stripe Individual",
        image=None,
        created_at=now,
        updated_at=now,
        scopes=[],
        stripe_customer_id=stripe_customer_id,
    )


def make_session(*, individual_id: UUID) -> FakeSession:
    now = datetime.now(UTC)
    return FakeSession(
        id=uuid4(),
        individual_id=individual_id,
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


def make_team(
    *,
    organization_id: UUID | None = None,
    team_id: UUID | None = None,
    stripe_customer_id: str | None = None,
) -> FakeTeam:
    now = datetime.now(UTC)
    return FakeTeam(
        id=uuid4() if team_id is None else team_id,
        organization_id=uuid4() if organization_id is None else organization_id,
        name="Platform",
        created_at=now,
        updated_at=now,
        stripe_customer_id=stripe_customer_id,
    )


def make_stripe_subscription(
    *,
    subscription_id: str = "sub_123",
    account_id: str = "cus_123",
    status: StripeSubscriptionStatus = "active",
    current_period_start: int | None = 1_710_000_000,
    current_period_end: int | None = 1_712_592_000,
    cancel_at_period_end: bool = False,
    cancel_at: int | None = None,
    canceled_at: int | None = None,
    ended_at: int | None = None,
    trial_start: int | None = None,
    trial_end: int | None = None,
    metadata: dict[str, str] | None = None,
    price_id: str = "price_pro",
    lookup_key: str | None = None,
    interval: StripeBillingInterval = "month",
    item_id: str = "si_123",
    quantity: int | None = 1,
    usage_type: str | None = None,
    schedule: str | None = None,
    items: list[dict[str, object]] | None = None,
) -> Subscription:
    subscription_items = (
        [
            {
                "id": item_id,
                "object": "subscription_item",
                "price": {
                    "id": price_id,
                    "object": "price",
                    "lookup_key": lookup_key,
                    "recurring": {
                        "interval": interval,
                        "usage_type": usage_type,
                    },
                },
                "quantity": quantity,
            },
        ]
        if items is None
        else items
    )
    return Subscription.construct_from(
        {
            "id": subscription_id,
            "object": "subscription",
            "customer": account_id,
            "status": status,
            "current_period_start": current_period_start,
            "current_period_end": current_period_end,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "cancel_at_period_end": cancel_at_period_end,
            "cancel_at": cancel_at,
            "canceled_at": canceled_at,
            "ended_at": ended_at,
            "schedule": schedule,
            "metadata": metadata or {},
            "items": {
                "object": "list",
                "data": subscription_items,
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


def make_price(
    *,
    price_id: str,
    lookup_key: str | None = None,
    interval: StripeBillingInterval = "month",
    usage_type: str | None = None,
) -> Price:
    return Price.construct_from(
        {
            "id": price_id,
            "object": "price",
            "lookup_key": lookup_key,
            "recurring": {
                "interval": interval,
                "usage_type": usage_type,
            },
        },
        key=None,
    )


def make_customer(
    *,
    customer_id: str = "cus_existing",
    email: str | None = None,
    name: str | None = None,
    metadata: dict[str, str] | None = None,
) -> Customer:
    return Customer.construct_from(
        {
            "id": customer_id,
            "object": "customer",
            "email": email,
            "name": name,
            "metadata": metadata or {},
        },
        key=None,
    )


def _metadata_dict(metadata: StripeObject | dict[str, str] | None) -> dict[str, str]:
    if metadata is None:
        return {}
    if isinstance(metadata, StripeObject):
        raw_metadata = metadata.to_dict()
        return {key: value for key, value in raw_metadata.items() if isinstance(value, str)}
    return metadata


def _stripe_dict(item: StripeObject) -> dict[str, object]:
    return item._to_dict_recursive()


def _list_object[T](items: list[T]) -> ListObject[T]:
    return ListObject._construct_from(
        values={
            "object": "list",
            "data": [_stripe_dict(item) for item in items],
            "has_more": False,
            "url": "/v1/customers",
        },
        requestor=None,
        api_mode="V1",
    )


def _subscription_items_list(
    *,
    subscription_id: str,
    items: list[dict[str, object]],
) -> ListObject[StripeObject]:
    return ListObject._construct_from(
        values={
            "object": "list",
            "data": items,
            "has_more": False,
            "url": f"/v1/subscription_items?subscription={subscription_id}",
        },
        requestor=None,
        api_mode="V1",
    )


def _extract_search_email(query: str) -> str | None:
    marker = 'email:"'
    if marker not in query:
        return None
    return query.split(marker, maxsplit=1)[1].split('"', maxsplit=1)[0].replace('\\"', '"')


def _extract_search_metadata(query: str, key: str) -> str | None:
    marker = f'metadata["{key}"]:"'
    if marker not in query:
        return None
    return query.split(marker, maxsplit=1)[1].split('"', maxsplit=1)[0]


def _apply_subscription_items_update(
    *,
    subscription: Subscription,
    items: list[SubscriptionUpdateParamsItem],
    sdk: FakeStripeSDK,
) -> None:
    current_items = [_stripe_dict(item) for item in subscription.items.data]
    by_id = {item["id"]: item for item in current_items}
    next_items: list[dict[str, object]] = []

    for update in items:
        item_id = update.get("id")
        if item_id is not None and update.get("deleted"):
            by_id.pop(item_id, None)
            continue
        if item_id is not None and item_id in by_id:
            item = by_id.pop(item_id)
            if (price_id := update.get("price")) is not None:
                price = sdk.price_responses.get(price_id) or make_price(price_id=price_id)
                sdk.price_responses[price_id] = price
                item["price"] = _stripe_dict(price)
            if "quantity" in update:
                item["quantity"] = update["quantity"]
            next_items.append(item)
            continue
        if (price_id := update.get("price")) is not None:
            price = sdk.price_responses.get(price_id) or make_price(price_id=price_id)
            sdk.price_responses[price_id] = price
            next_items.append(
                {
                    "id": f"si_generated_{len(next_items) + 1}",
                    "object": "subscription_item",
                    "price": _stripe_dict(price),
                    "quantity": update.get("quantity"),
                },
            )

    next_items.extend(by_id.values())
    subscription["items"] = _subscription_items_list(
        subscription_id=subscription.id,
        items=next_items,
    )
