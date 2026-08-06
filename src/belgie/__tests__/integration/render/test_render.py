from __future__ import annotations

import json
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from langchain.tools import ToolRuntime
from langgraph.runtime import Runtime as LangGraphRuntime
from pydantic_ai.exceptions import ModelRetry

from belgie import Environment
from belgie.__tests__.integration.render.conftest import VITE_PACKAGE_ROOT
from belgie.agent import BelgieRuntimeSession, _runtime as agent_runtime
from belgie.agent._run_code import RENDER_WIDGET_TOOL_NAME
from belgie.errors import BelgieJavaScriptError
from belgie.langchain import BelgieMiddleware
from belgie.pydantic_ai import BelgieSandbox, BelgieSandboxSession, _session as pydantic_session
from belgie.pydantic_ai._toolset import BelgieSandboxToolset

if TYPE_CHECKING:
    from belgie.langchain._state import BelgieAgentState

pytestmark = pytest.mark.integration

SKIP_WIN32_VITE_NATIVE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Rolldown's napi-sys falls back to libnode.dll, unavailable in embedded Deno",
)
INLINE_WIDGET_SOURCE: Final[str] = """
export default function Widget() {
  return <main data-kind="inline">plugin-target</main>;
}
"""


def copy_vite_package(root: Path) -> Path:
    package = root / "vendor" / "vite"
    package.mkdir(parents=True)
    shutil.copy2(VITE_PACKAGE_ROOT / "package.json", package / "package.json")
    shutil.copytree(VITE_PACKAGE_ROOT / "dist", package / "dist")
    return package


def write_plugin_package(root: Path, *, name: str, body: str) -> Path:
    package = root / "vendor" / name
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": name, "version": "0.0.0", "type": "module", "exports": {".": "./index.js"}}),
        encoding="utf-8",
    )
    (package / "index.js").write_text(body, encoding="utf-8")
    return package


@pytest.fixture
def default_render_specifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    package = copy_vite_package(tmp_path)
    specifier = f"file:{package}"

    def render_dependencies(plugins: tuple[str, ...]) -> dict[str, str]:
        dependencies = {
            "@belgie/vite": specifier,
            "react": "npm:react@19.2.8",
            "react-dom": "npm:react-dom@19.2.8",
        }
        for plugin in plugins:
            name = agent_runtime._package_name_from_specifier(plugin)
            dependencies[name] = agent_runtime._dependency_specifier(plugin)
        return dependencies

    monkeypatch.setattr(agent_runtime, "DEFAULT_RENDER_SPECIFIER", specifier)
    monkeypatch.setattr(agent_runtime, "_render_dependencies", render_dependencies)
    return package


def workspace_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def path_exists(path: Path) -> bool:
    return path.exists()


def path_is_dir(path: Path) -> bool:
    return path.is_dir()


def patch_pydantic_render_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    package: Path,
    *,
    extra: dict[str, str] | None = None,
) -> None:
    dependencies = {
        "@belgie/vite": f"file:{package}",
        "react": "npm:react@19.2.8",
        "react-dom": "npm:react-dom@19.2.8",
    }
    if extra:
        dependencies.update(extra)
    monkeypatch.setattr(pydantic_session, "DEFAULT_RENDER_DEPENDENCIES", dependencies)


@asynccontextmanager
async def active_pydantic_toolset(capability: BelgieSandbox[Any]) -> AsyncIterator[BelgieSandboxToolset[Any]]:
    toolset = capability.get_toolset()
    assert isinstance(toolset, BelgieSandboxToolset)
    run_toolset = await toolset.for_run(cast("Any", None))
    assert isinstance(run_toolset, BelgieSandboxToolset)
    async with run_toolset:
        yield run_toolset


def tool_runtime(state: BelgieAgentState) -> ToolRuntime[Any, BelgieAgentState]:
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="call_1",
        store=None,
    )


@asynccontextmanager
async def active_langchain_state(middleware: BelgieMiddleware) -> AsyncIterator[BelgieAgentState]:
    state: BelgieAgentState = {"messages": []}
    update = await middleware.abefore_agent(state, LangGraphRuntime(context=None))
    if update:
        state.update(cast("BelgieAgentState", update))
    try:
        yield state
    finally:
        await middleware.aafter_agent(state, LangGraphRuntime(context=None))


@SKIP_WIN32_VITE_NATIVE
async def test_pydantic_ai_and_langchain_return_the_same_inline_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_vite_package(root)
    plugin = write_plugin_package(
        root,
        name="server-plugin",
        body="""\
export default function serverPlugin() {
  return {
    name: "server-only-plugin-marker",
    renderChunk(code) {
      return code.replace("plugin-target", "plugin-applied");
    },
  };
}
""",
    )
    patch_pydantic_render_dependencies(monkeypatch, package, extra={"server-plugin": f"file:{plugin}"})
    monkeypatch.setattr(
        pydantic_session,
        "_render_dependencies",
        lambda plugins: {
            **pydantic_session.DEFAULT_RENDER_DEPENDENCIES,
            **dict.fromkeys(plugins, f"file:{plugin}"),
        },
    )
    environment = Environment(
        {
            "@belgie/vite": f"file:{package}",
            "react": "npm:react@19.2.8",
            "react-dom": "npm:react-dom@19.2.8",
            "server-plugin": f"file:{plugin}",
        },
        path=root,
    )
    options = agent_runtime._script_runtime_options(root)

    async with BelgieSandboxSession(enable_rendering=True, plugins=("server-plugin",)) as pydantic_session_instance:
        pydantic_result = await pydantic_session_instance.render_widget(INLINE_WIDGET_SOURCE)

    async with environment as active_environment:
        await active_environment.install()
        files_before = workspace_files(root)
        middleware = BelgieMiddleware(
            environment=active_environment,
            runtime_options=options,
            plugins=("server-plugin",),
        )
        render_widget = next(tool for tool in middleware.tools if tool.name == RENDER_WIDGET_TOOL_NAME)
        async with active_langchain_state(middleware) as state:
            langchain_result = await render_widget.ainvoke(
                {"source": INLINE_WIDGET_SOURCE, "runtime": tool_runtime(state)},
            )

        files_after = workspace_files(root)

    assert isinstance(pydantic_result, str)
    assert pydantic_result == langchain_result
    assert pydantic_result.startswith("<!doctype html>")
    assert "plugin-applied" in pydantic_result
    assert "server-only-plugin-marker" not in pydantic_result
    assert '<script type="module" src=' not in pydantic_result
    assert files_after == files_before


@SKIP_WIN32_VITE_NATIVE
async def test_pydantic_ai_session_renders_inline_widget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_vite_package(root)
    plugin = write_plugin_package(
        root,
        name="server-plugin",
        body="""\
export default function serverPlugin() {
  return {
    name: "server-only-plugin-marker",
    renderChunk(code) {
      return code.replace("plugin-target", "plugin-applied");
    },
  };
}
""",
    )
    patch_pydantic_render_dependencies(monkeypatch, package, extra={"server-plugin": f"file:{plugin}"})
    monkeypatch.setattr(
        pydantic_session,
        "_render_dependencies",
        lambda plugins: {
            **pydantic_session.DEFAULT_RENDER_DEPENDENCIES,
            **dict.fromkeys(plugins, f"file:{plugin}"),
        },
    )

    async with BelgieSandboxSession(enable_rendering=True, plugins=("server-plugin",)) as session:
        result = await session.render_widget(INLINE_WIDGET_SOURCE)

    assert isinstance(result, str)
    assert result.startswith("<!doctype html>")
    assert "plugin-applied" in result
    assert "server-only-plugin-marker" not in result


@SKIP_WIN32_VITE_NATIVE
async def test_default_session_renders_inline_widget(default_render_specifier: Path) -> None:
    del default_render_specifier
    session = BelgieRuntimeSession()
    async with session:
        result = await session.render_widget(
            "export default function Widget() { return <main>Hello from Belgie</main>; }",
        )

    assert isinstance(result, str)
    assert result.startswith("<!doctype html>")
    assert "Hello from Belgie" in result


@SKIP_WIN32_VITE_NATIVE
async def test_plugins_resolve_from_workspace_packages(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_vite_package(root)
    plugin = write_plugin_package(
        root,
        name="workspace-plugin",
        body="""\
export default function makePlugin() {
  return {
    name: "workspace-plugin",
    renderChunk(code) {
      return code.replace("workspace-target", "workspace-applied");
    },
  };
}
""",
    )
    source = """
export default function Widget() {
  return <main>workspace-target</main>;
}
"""
    environment = Environment(
        {
            "@belgie/vite": f"file:{package}",
            "react": "npm:react@19.2.8",
            "react-dom": "npm:react-dom@19.2.8",
            "workspace-plugin": f"file:{plugin}",
        },
        path=root,
    )
    options = agent_runtime._script_runtime_options(root)

    async with environment as active_environment:
        await active_environment.install()
        session = BelgieRuntimeSession(
            environment=active_environment,
            runtime_options=options,
            plugins=("workspace-plugin",),
        )
        async with session:
            result = await session.render_widget(source)

    assert isinstance(result, str)
    assert result.startswith("<!doctype html>")
    assert "workspace-applied" in result
    assert "workspace-target" not in result


@SKIP_WIN32_VITE_NATIVE
async def test_default_session_is_temporary_and_denies_host_capabilities(
    tmp_path: Path,
    default_render_specifier: Path,
) -> None:
    del default_render_specifier
    secret = tmp_path / "secret.txt"
    secret.write_text("outside-secret", encoding="utf-8")
    session = BelgieRuntimeSession()

    async with session:
        workspace = session._workspace
        assert workspace is not None
        output = workspace / "source.tsx"
        assert path_is_dir(workspace)
        with pytest.raises(BelgieJavaScriptError, match="Requires read access"):
            await session.run_script(
                f"export default function run() {{ return Deno.readTextFileSync({secret.as_posix()!r}); }}",
            )
        with pytest.raises(BelgieJavaScriptError, match="Requires write access"):
            await session.run_script(
                f"export default function run() {{ Deno.writeTextFileSync({output.as_posix()!r}, 'changed'); }}",
            )
        with pytest.raises(BelgieJavaScriptError, match="Requires env access"):
            await session.run_script(
                'export default function run() { return Deno.env.get("HOME"); }',
            )
        with pytest.raises(BelgieJavaScriptError, match="Requires run access"):
            await session.run_script(
                'export default function run() { return new Deno.Command("echo").outputSync(); }',
            )
        if sys.platform != "win32":
            with pytest.raises(BelgieJavaScriptError, match="Requires read access"):
                await session.run_script(
                    'export default function run() { return Deno.readTextFileSync("/proc/self/environ"); }',
                )
            with pytest.raises(BelgieJavaScriptError, match="Requires read access"):
                await session.run_script(
                    'export default function run() { return Deno.readTextFileSync("/etc/passwd"); }',
                )
            with pytest.raises(BelgieJavaScriptError, match="Requires ffi access"):
                await session.run_script(
                    "export default function run() { return Deno.dlopen('libc.so.6', {}); }",
                )

    assert secret.read_text(encoding="utf-8") == "outside-secret"
    assert not path_exists(output)
    assert not path_exists(workspace)


@SKIP_WIN32_VITE_NATIVE
async def test_pydantic_render_widget_reports_render_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_vite_package(root)
    broken = write_plugin_package(
        root,
        name="broken-plugin",
        body="""\
export default function broken() {
  return {
    name: "broken",
    buildStart() {
      throw new Error("vite-plugin-failure");
    },
  };
}
""",
    )
    patch_pydantic_render_dependencies(monkeypatch, package, extra={"broken-plugin": f"file:{broken}"})
    monkeypatch.setattr(
        pydantic_session,
        "_render_dependencies",
        lambda plugins: {
            **pydantic_session.DEFAULT_RENDER_DEPENDENCIES,
            **{name: pydantic_session.DEFAULT_RENDER_DEPENDENCIES.get(name, f"npm:{name}") for name in plugins},
        },
    )

    async with active_pydantic_toolset(BelgieSandbox(enable_rendering=True)) as toolset:
        with pytest.raises(ModelRetry, match="Command exited with status 1"):
            await toolset.render_widget("export function Widget() { return null; }")

    async with active_pydantic_toolset(
        BelgieSandbox(enable_rendering=True, plugins=("broken-plugin",)),
    ) as toolset:
        with pytest.raises(ModelRetry, match="Command exited with status 1"):
            await toolset.render_widget("export default function Widget() { return <main />; }")


@SKIP_WIN32_VITE_NATIVE
async def test_pydantic_render_widget_uses_timeout_retry_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_vite_package(root)
    waiting = write_plugin_package(
        root,
        name="wait-plugin",
        body="""\
export default function waitForever() {
  return {
    name: "wait-forever",
    buildStart() {
      return new Promise((resolve) => setTimeout(resolve, 10_000));
    },
  };
}
""",
    )
    patch_pydantic_render_dependencies(monkeypatch, package, extra={"wait-plugin": f"file:{waiting}"})
    monkeypatch.setattr(
        pydantic_session,
        "_render_dependencies",
        lambda plugins: {
            **pydantic_session.DEFAULT_RENDER_DEPENDENCIES,
            **dict.fromkeys(plugins, f"file:{waiting}"),
        },
    )

    async with active_pydantic_toolset(
        BelgieSandbox(enable_rendering=True, plugins=("wait-plugin",), timeout=5.0),
    ) as toolset:
        with pytest.raises(ModelRetry, match="timed out after 5.0 seconds"):
            await toolset.render_widget("export default function Widget() { return <main />; }")
