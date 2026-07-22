from __future__ import annotations

import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from langchain.tools import ToolRuntime
from langgraph.runtime import Runtime as LangGraphRuntime
from pydantic_ai import AbstractToolset, RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.usage import RunUsage

from belgie import Environment, RuntimeOptions, RuntimePermissions
from belgie.agent import RUN_CODE_TOOL_NAME, BelgieRuntimeSession, _runtime as agent_runtime
from belgie.errors import BelgieJavaScriptError
from belgie.langchain import BelgieMiddleware
from belgie.pydantic_ai._toolset import BelgieToolset

if TYPE_CHECKING:
    from belgie.langchain._state import BelgieAgentState

pytestmark = pytest.mark.integration

SKIP_WIN32_VITE_NATIVE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Vite build loads Rolldown's native Node-API addon",
)
RENDER_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "render"
VITE_SYS_PERMISSIONS: Final[tuple[str, ...]] = (
    "homedir",
    "uid",
    "gid",
    "cpus",
    "osRelease",
    "systemMemoryInfo",
)
VITE_READ_PATHS: Final[tuple[str, ...]] = (
    ()
    if sys.platform == "win32"
    else (
        "/etc",
        "/proc",
        "/usr/bin/ldd",
    )
)
INLINE_WIDGET_SOURCE: Final[str] = """
import { render } from "@belgie/render";

const serverOnlyMarker = "server-only-plugin-marker";

function serverPlugin() {
  return {
    name: serverOnlyMarker,
    renderChunk(code) {
      return code.replace("plugin-target", "plugin-applied");
    },
  };
}

function Widget() {
  return <main data-kind="inline">plugin-target</main>;
}

export default function run() {
  return render({
    widget: <Widget />,
    plugins: [serverPlugin()],
  });
}
"""


class EmptyToolset(AbstractToolset[None]):
    @property
    def id(self) -> str | None:
        return None

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:  # noqa: ARG002
        return {}

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],  # noqa: ARG002
        ctx: RunContext[None],  # noqa: ARG002
        tool: ToolsetTool[None],  # noqa: ARG002
    ) -> Any:
        msg = f"unexpected wrapped tool call: {name}"
        raise AssertionError(msg)


def run_context() -> RunContext[None]:
    return RunContext[None](
        deps=None,
        model=TestModel(),
        usage=RunUsage(),
        prompt=None,
        messages=[],
        run_step=0,
        pending_messages=[],
    )


def secure_runtime_options(root: Path) -> RuntimeOptions:
    return RuntimeOptions(
        permissions=RuntimePermissions(
            allow_ffi=[str(root / "node_modules")],
            allow_net=[],
            allow_read=[str(root), *VITE_READ_PATHS],
            allow_sys=VITE_SYS_PERMISSIONS,
        ),
    )


def copy_render_package(root: Path) -> Path:
    package = root / "vendor" / "render"
    package.mkdir(parents=True)
    shutil.copy2(RENDER_PACKAGE_ROOT / "package.json", package / "package.json")
    shutil.copytree(RENDER_PACKAGE_ROOT / "dist", package / "dist")
    return package


@pytest.fixture
def default_render_specifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    package = copy_render_package(tmp_path)
    monkeypatch.setattr(agent_runtime, "DEFAULT_RENDER_SPECIFIER", f"file:{package}")
    return package


def workspace_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def path_exists(path: Path) -> bool:
    return path.exists()


def path_is_dir(path: Path) -> bool:
    return path.is_dir()


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
async def test_pydantic_ai_and_langchain_return_the_same_inline_html(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_render_package(root)
    environment = Environment({"@belgie/render": f"file:{package}"}, path=root)
    options = secure_runtime_options(root)

    async with environment as active_environment:
        await active_environment.install()
        files_before = workspace_files(root)
        context = run_context()
        toolset = BelgieToolset(
            wrapped=EmptyToolset(),
            environment=active_environment,
            runtime_options=options,
        )
        async with toolset:
            tools = await toolset.get_tools(context)
            pydantic_result = await toolset.call_tool(
                RUN_CODE_TOOL_NAME,
                {"code": INLINE_WIDGET_SOURCE},
                context,
                tools[RUN_CODE_TOOL_NAME],
            )

        middleware = BelgieMiddleware(environment=active_environment, runtime_options=options)
        run_code = next(tool for tool in middleware.tools if tool.name == RUN_CODE_TOOL_NAME)
        async with active_langchain_state(middleware) as state:
            langchain_result = await run_code.ainvoke(
                {"code": INLINE_WIDGET_SOURCE, "runtime": tool_runtime(state)},
            )

        files_after = workspace_files(root)

    assert isinstance(pydantic_result, ToolReturn)
    assert isinstance(pydantic_result.return_value, str)
    assert pydantic_result.return_value == langchain_result
    assert pydantic_result.return_value.startswith("<!doctype html>")
    assert "plugin-applied" in pydantic_result.return_value
    assert "server-only-plugin-marker" not in pydantic_result.return_value
    assert '<script type="module" src=' not in pydantic_result.return_value
    assert files_after == files_before


@SKIP_WIN32_VITE_NATIVE
async def test_environment_session_uses_isolated_runtime_options_by_default(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_render_package(root)
    environment = Environment({"@belgie/render": f"file:{package}"}, path=root)

    async with environment as active_environment:
        await active_environment.install()
        context = run_context()
        toolset = BelgieToolset(wrapped=EmptyToolset(), environment=active_environment)
        async with toolset:
            tools = await toolset.get_tools(context)
            result = await toolset.call_tool(
                RUN_CODE_TOOL_NAME,
                {"code": INLINE_WIDGET_SOURCE},
                context,
                tools[RUN_CODE_TOOL_NAME],
            )

    assert isinstance(result, ToolReturn)
    assert isinstance(result.return_value, str)
    assert result.return_value.startswith("<!doctype html>")
    assert "plugin-applied" in result.return_value
    assert "server-only-plugin-marker" not in result.return_value


@SKIP_WIN32_VITE_NATIVE
async def test_default_session_renders_inline_widget(default_render_specifier: Path) -> None:
    session = BelgieRuntimeSession()
    async with session:
        result = await session.run_script(INLINE_WIDGET_SOURCE)

    assert isinstance(result, str)
    assert result.startswith("<!doctype html>")
    assert "plugin-applied" in result
    assert "server-only-plugin-marker" not in result


@SKIP_WIN32_VITE_NATIVE
async def test_default_session_is_temporary_and_denies_host_capabilities(
    tmp_path: Path,
    default_render_specifier: Path,
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("outside-secret", encoding="utf-8")
    session = BelgieRuntimeSession()

    async with session:
        workspace = Path(
            cast(
                "str",
                await session.run_script(
                    "export default function run() { "
                    'const context = globalThis[Symbol.for("@belgie/render/context")]; '
                    'return decodeURIComponent(new URL(".", context.url).pathname); }',
                ),
            ),
        )
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

    assert secret.read_text(encoding="utf-8") == "outside-secret"
    assert not path_exists(output)
    assert not path_exists(workspace)


@SKIP_WIN32_VITE_NATIVE
async def test_vite_failures_and_invalid_elements_use_existing_pydantic_error_path(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_render_package(root)
    environment = Environment({"@belgie/render": f"file:{package}"}, path=root)

    async with environment as active_environment:
        await active_environment.install()
        context = run_context()
        toolset = BelgieToolset(
            wrapped=EmptyToolset(),
            environment=active_environment,
            runtime_options=secure_runtime_options(root),
        )
        async with toolset:
            tools = await toolset.get_tools(context)
            with pytest.raises(ModelRetry, match="widget must be a React element"):
                await toolset.call_tool(
                    RUN_CODE_TOOL_NAME,
                    {
                        "code": (
                            'import { render } from "@belgie/render"; '
                            'export default () => render({ widget: "invalid" });'
                        ),
                    },
                    context,
                    tools[RUN_CODE_TOOL_NAME],
                )
            with pytest.raises(ModelRetry, match="vite-plugin-failure"):
                await toolset.call_tool(
                    RUN_CODE_TOOL_NAME,
                    {
                        "code": """
import { render } from "@belgie/render";
const broken = { name: "broken", buildStart() { throw new Error("vite-plugin-failure"); } };
export default () => render({ widget: <main />, plugins: [broken] });
""",
                    },
                    context,
                    tools[RUN_CODE_TOOL_NAME],
                )


@SKIP_WIN32_VITE_NATIVE
async def test_inline_vite_build_uses_existing_timeout_path(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    package = copy_render_package(root)
    environment = Environment({"@belgie/render": f"file:{package}"}, path=root)

    async with environment as active_environment:
        await active_environment.install()
        context = run_context()
        toolset = BelgieToolset(
            wrapped=EmptyToolset(),
            environment=active_environment,
            runtime_options=secure_runtime_options(root),
            timeout=1.0,
        )
        async with toolset:
            tools = await toolset.get_tools(context)
            with pytest.raises(ModelRetry, match="timed out after 1.0 seconds"):
                await toolset.call_tool(
                    RUN_CODE_TOOL_NAME,
                    {
                        "code": """
import { render } from "@belgie/render";
const waitForever = {
  name: "wait-forever",
  buildStart() { return new Promise((resolve) => setTimeout(resolve, 10_000)); },
};
export default () => render({ widget: <main />, plugins: [waitForever] });
""",
                    },
                    context,
                    tools[RUN_CODE_TOOL_NAME],
                )
