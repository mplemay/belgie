from __tests__.alchemy.conftest import User


def test_primary_key_mixin_defaults() -> None:
    id_column = User.__table__.c.id  # type: ignore[attr-defined]
    assert id_column.primary_key
    assert str(id_column.server_default.arg) == "gen_random_uuid()"
    assert id_column.index


def test_timestamp_mixin_defaults() -> None:
    user = User(email="defaults@example.com")
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.deleted_at is None


def test_mark_deleted_sets_timestamp() -> None:
    user = User(email="x@example.com")
    assert user.deleted_at is None
    user.mark_deleted()
    assert user.deleted_at is not None
