from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from __tests__.alchemy.conftest import User
from belgie.alchemy.repository import RepositoryBase, RepositoryIDMixin, RepositorySoftDeletionMixin


class UserRepository(
    RepositorySoftDeletionMixin[User],
    RepositoryIDMixin[User, UUID],
    RepositoryBase[User],
):
    model = User


@pytest.mark.asyncio
async def test_create_and_get_by_id(alchemy_session: AsyncSession) -> None:
    repo = UserRepository(session=alchemy_session)
    user = User(email="repo@example.com")
    await repo.create(user, flush=True)
    await alchemy_session.commit()

    found = await repo.get_by_id(user.id)
    assert found is not None
    assert found.email == "repo@example.com"


@pytest.mark.asyncio
async def test_soft_delete_filters_from_base(alchemy_session: AsyncSession) -> None:
    repo = UserRepository(session=alchemy_session)
    user = User(email="soft@example.com")
    await repo.create(user, flush=True)
    await repo.soft_delete(user, flush=True)
    await alchemy_session.commit()

    hidden = await repo.one_or_none(repo.base.where(User.id == user.id))
    assert hidden is None

    visible = await repo.one_or_none(repo.all.where(User.id == user.id))
    assert visible is not None


@pytest.mark.asyncio
async def test_paginate_returns_total(alchemy_session: AsyncSession) -> None:
    repo = UserRepository(session=alchemy_session)
    for i in range(15):
        user = User(email=f"p{i}@example.com")
        await repo.create(user)
    await alchemy_session.commit()

    stmt = repo.base.order_by(User.email)
    page1, total = await repo.paginate(stmt, limit=10, page=1)
    page2, total2 = await repo.paginate(stmt, limit=10, page=2)

    assert total == 15
    assert total2 == 15
    assert len(page1) == 10
    assert len(page2) == 5
