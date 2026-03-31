from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.fixtures.core.models import Account, Individual, OAuthState, Session


def test_individual_model_structure() -> None:
    """Verify Individual model demonstrates proper structure."""
    assert Individual.__tablename__ == "individual"
    assert not Individual.__dict__.get("__abstract__", False)
    assert hasattr(Individual, "email")
    assert hasattr(Individual, "scopes")


def test_individual_has_scopes_field() -> None:
    """Verify Individual has scopes field that defaults to an empty list and accepts list assignment."""
    individual = Individual(email="test@example.com")
    assert individual.scopes == []
    individual.scopes = ["read", "write"]
    assert individual.scopes == ["read", "write"]


def test_individual_relationships_defined() -> None:
    """Verify Individual has bidirectional relationships defined."""
    assert hasattr(Individual, "accounts")
    assert hasattr(Individual, "sessions")
    assert hasattr(Individual, "oauth_states")


@pytest.mark.asyncio
async def test_account_unique_constraint(alchemy_session: AsyncSession) -> None:
    individual = Individual(email="auth@example.com")
    alchemy_session.add(individual)
    await alchemy_session.commit()

    account = Account(
        individual_id=individual.id,
        provider="google",
        provider_account_id="abc",
    )
    alchemy_session.add(account)
    await alchemy_session.commit()

    duplicate = Account(
        individual_id=individual.id,
        provider="google",
        provider_account_id="abc",
    )
    alchemy_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await alchemy_session.commit()
    await alchemy_session.rollback()


@pytest.mark.asyncio
async def test_session_relationship(alchemy_session: AsyncSession) -> None:
    individual = Individual(email="session@example.com")
    alchemy_session.add(individual)
    await alchemy_session.commit()

    session = Session(
        individual_id=individual.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    alchemy_session.add(session)
    await alchemy_session.commit()

    refreshed = await alchemy_session.get(Individual, individual.id)
    assert refreshed is not None
    await alchemy_session.refresh(refreshed, attribute_names=["sessions"])
    assert len(refreshed.sessions) == 1


@pytest.mark.asyncio
async def test_oauth_state_optional_individual(alchemy_session: AsyncSession) -> None:
    state = OAuthState(
        state="abc",
        code_verifier=None,
        redirect_url=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        individual_id=None,
    )
    alchemy_session.add(state)
    await alchemy_session.commit()

    rows = await alchemy_session.execute(select(OAuthState))
    stored = rows.scalar_one()
    assert stored.individual is None
