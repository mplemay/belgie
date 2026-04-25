from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.stripe import StripeAccountProtocol

SCHEDULE_OWNER = "belgie-stripe"


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
