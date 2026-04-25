from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from belgie_proto.core.account import AccountType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from belgie_proto.stripe import StripeAccountProtocol

SCHEDULE_OWNER = "belgie-stripe"


@dataclass(slots=True, kw_only=True, frozen=True)
class ParsedCustomerMetadata:
    raw: dict[str, str]
    account_id: UUID | None
    account_type: AccountType | None


@dataclass(slots=True, kw_only=True, frozen=True)
class ParsedSubscriptionMetadata(ParsedCustomerMetadata):
    local_subscription_id: UUID | None
    plan: str | None


@dataclass(slots=True, kw_only=True, frozen=True)
class ParsedScheduleMetadata(ParsedSubscriptionMetadata):
    managed_by: str | None

    @property
    def is_managed_by_plugin(self) -> bool:
        return self.managed_by == SCHEDULE_OWNER


def customer_metadata(
    *,
    account: StripeAccountProtocol,
    metadata: dict[str, str],
) -> dict[str, str]:
    return {
        **metadata,
        "account_id": str(account.id),
        "account_type": account.account_type,
    }


def subscription_metadata(
    *,
    account: StripeAccountProtocol,
    subscription_id: UUID,
    plan: str,
    metadata: dict[str, str],
) -> dict[str, str]:
    return {
        **metadata,
        "account_id": str(account.id),
        "account_type": account.account_type,
        "local_subscription_id": str(subscription_id),
        "plan": plan,
    }


def schedule_metadata(
    *,
    account: StripeAccountProtocol,
    subscription_id: UUID,
    plan: str,
) -> dict[str, str]:
    return {
        **subscription_metadata(
            account=account,
            subscription_id=subscription_id,
            plan=plan,
            metadata={},
        ),
        "managed_by": SCHEDULE_OWNER,
    }


def parse_customer_metadata(
    metadata: Mapping[str, str] | None,
) -> ParsedCustomerMetadata:
    raw = {} if metadata is None else dict(metadata)
    return ParsedCustomerMetadata(
        raw=raw,
        account_id=_parse_uuid(raw.get("account_id")),
        account_type=_parse_account_type(raw.get("account_type")),
    )


def parse_subscription_metadata(
    metadata: Mapping[str, str] | None,
) -> ParsedSubscriptionMetadata:
    parsed_customer = parse_customer_metadata(metadata)
    return ParsedSubscriptionMetadata(
        raw=parsed_customer.raw,
        account_id=parsed_customer.account_id,
        account_type=parsed_customer.account_type,
        local_subscription_id=_parse_uuid(parsed_customer.raw.get("local_subscription_id")),
        plan=parsed_customer.raw.get("plan"),
    )


def parse_schedule_metadata(
    metadata: Mapping[str, str] | None,
) -> ParsedScheduleMetadata:
    parsed_subscription = parse_subscription_metadata(metadata)
    return ParsedScheduleMetadata(
        raw=parsed_subscription.raw,
        account_id=parsed_subscription.account_id,
        account_type=parsed_subscription.account_type,
        local_subscription_id=parsed_subscription.local_subscription_id,
        plan=parsed_subscription.plan,
        managed_by=parsed_subscription.raw.get("managed_by"),
    )


def _parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _parse_account_type(value: str | None) -> AccountType | None:
    if value is None:
        return None
    try:
        return AccountType(value)
    except ValueError:
        return None
