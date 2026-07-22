from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from belgie import Environment, Runtime, Script
from belgie.errors import BelgieJavaScriptError
from belgie.widget import WidgetBuilder, WidgetSource
from belgie.widget._builder import BUILDER_DEPENDENCIES, _runtime_options

pytestmark = pytest.mark.integration

WIDGET: Final[WidgetSource] = WidgetSource(
    widget="""
import "./styles.css";
import { WeatherCard } from "./weather-card";
import weather from "./weather.json";

export default function WeatherWidget() {
  return <WeatherCard city={weather.city} temperature={weather.temperature} />;
}
""".lstrip(),
    files={
        "weather-card.tsx": """
export function WeatherCard(props: { city: string; temperature: number }) {
  return <section className="weather">{props.city}: {props.temperature}°</section>;
}
""".lstrip(),
        "styles.css": ".weather { color: rebeccapurple; }\n",
        "weather.json": '{"city":"Austin","temperature":32}\n',
    },
)

PERMISSION_PROBE: Final[Script[[], dict[str, str]]] = Script(
    """
export default async function run() {
  const denied = async (action) => {
    try {
      await action();
      return "granted";
    } catch (error) {
      return error instanceof Deno.errors.NotCapable ? "denied" : error.constructor.name;
    }
  };
  return {
    write: await denied(() => Deno.writeTextFile("/tmp/belgie-widget-denied", "denied")),
    net: await denied(() => fetch("https://example.com")),
    run: await denied(() => new Deno.Command("echo").output()),
    import: await denied(() => import("https://example.com/module.ts")),
    env: await denied(() => Deno.env.get("HOME")),
  };
}
""",
)


def test_sync_builder_reuses_environment_and_leaves_no_project_files(
    widget_environment_factory: Callable[[str], Environment],
) -> None:
    environment = widget_environment_factory("sync")
    with WidgetBuilder(environment=environment) as builder:
        first = builder.build(WIDGET)
        second = builder.build(WIDGET)
        root = environment.workspace
        assert list(root.glob(".belgie-widget-project-*"))

    assert first == second
    assert first.html.startswith("<!doctype html>")
    assert "#639" in first.html
    assert "Austin" in first.html
    assert not list(root.glob(".belgie-widget-project-*"))
    assert not (root / "src").exists()
    assert not (root / "dist").exists()


def test_default_builder_removes_its_temporary_environment(
    local_builder_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        BUILDER_DEPENDENCIES,
        "@belgie/mcp",
        f"file:{local_builder_package.as_posix()}",
    )

    with WidgetBuilder() as builder:
        bundle = builder.build(WIDGET)
        assert builder._root is not None
        environment_root = builder._root.parent
        assert environment_root.exists()

    assert bundle.html.startswith("<!doctype html>")
    assert not environment_root.exists()


async def test_async_builder_normalizes_virtual_diagnostics(
    widget_environment_factory: Callable[[str], Environment],
) -> None:
    environment = widget_environment_factory("async")
    source = WidgetSource(widget='import Missing from "./Missing"; export default Missing;')

    async with WidgetBuilder(environment=environment) as builder:
        with pytest.raises(BelgieJavaScriptError, match=r"Missing.*widget\.tsx"):
            await builder.build(source)


def test_sync_builder_enforces_timeout(
    widget_environment_factory: Callable[[str], Environment],
) -> None:
    environment = widget_environment_factory("sync-timeout")
    with (
        WidgetBuilder(environment=environment, timeout=0.000001) as builder,
        pytest.raises(TimeoutError, match="exceeded the 1e-06 second timeout"),
    ):
        builder.build(WIDGET)


async def test_async_builder_enforces_timeout(
    widget_environment_factory: Callable[[str], Environment],
) -> None:
    environment = widget_environment_factory("async-timeout")
    async with WidgetBuilder(environment=environment, timeout=0.000001) as builder:
        with pytest.raises(TimeoutError, match="exceeded the 1e-06 second timeout"):
            await builder.build(WIDGET)


def test_builder_runtime_denies_effectful_permissions(
    widget_environment_factory: Callable[[str], Environment],
) -> None:
    environment = widget_environment_factory("permissions")
    with environment as active_environment:
        active_environment.install()
        root = active_environment.workspace
        with Runtime(env=active_environment, options=_runtime_options(root)) as runtime:
            permissions = runtime(PERMISSION_PROBE)()

    assert permissions == {
        "write": "denied",
        "net": "denied",
        "run": "denied",
        "import": "TypeError",
        "env": "denied",
    }
