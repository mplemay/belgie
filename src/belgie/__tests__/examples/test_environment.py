import pytest

pytestmark = pytest.mark.integration


def test_environment_example_resolves_jsr_import_sync(environment_module) -> None:
    assert environment_module.resolve_join_export() == "join"


async def test_environment_example_resolves_jsr_import_async(environment_module) -> None:
    assert await environment_module.resolve_join_export_async() == "join"
