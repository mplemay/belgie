import pytest

pytestmark = pytest.mark.integration


async def test_parallel_weather_via_run_javascript(pydantic_ai_demo_module) -> None:
    assert await pydantic_ai_demo_module.run_javascript_parallel_demo() == {"paris": 22.2, "tokyo": 22.2}
