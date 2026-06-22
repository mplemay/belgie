from __future__ import annotations

import asyncio
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from json import dumps
from os import PathLike, environ
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from anyio import Path as AsyncPath

from belgie import Command, Environment, Runtime, Script
from belgie.errors import BelgieRuntimeError

if TYPE_CHECKING:
    from pathlib import Path

    from belgie._core import AsyncEnvironment

pytestmark = pytest.mark.integration

VITE_VERSION: Final[str] = "6.1.0"
ZX_VERSION: Final[str] = "8.5.5"
REACT_VERSION: Final[str] = "^19"
VITE_REACT_PLUGIN_VERSION: Final[str] = "^4"


@asynccontextmanager
async def installed_environment(
    dependencies: dict[str, str],
    *,
    install_path: str | PathLike[str] | None = None,
) -> AsyncIterator[AsyncEnvironment]:
    async with Environment(dependencies, path=install_path) as env:
        await env.install()
        yield env


async def test_runs_dependency_alias_without_external_node_or_deno(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        result = await runtime(Command("vite"))("--version")

    assert result is None


async def test_runs_explicit_npm_command_bin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        await runtime(Command(f"npm:vite@{VITE_VERSION}/vite"))("--version")


async def test_runs_command_from_isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    async with installed_environment({"semver": "7.7.2"}) as env, Runtime(env=env) as runtime:
        await runtime(Command("semver"))("--help")


async def test_runs_command_from_frozen_lockfile_environment_without_external_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    lockfile = tmp_path / "deno.lock"
    dependencies = {"semver": "7.7.2"}
    async with Environment(dependencies) as env:
        await env.lock(lockfile=lockfile)

    original_lock = lockfile.read_text(encoding="utf-8")
    monkeypatch.setenv("PATH", "")
    async with Environment(dependencies, lockfile=lockfile) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            await runtime(Command("semver"))("--help")

    assert lockfile.read_text(encoding="utf-8") == original_lock


async def test_environment_path_persists_command_files_across_recreation(
    isolated_project_cwd: Path,
) -> None:
    (isolated_project_cwd / "persist.mjs").write_text(
        """
import { writeFileSync } from "node:fs";

writeFileSync("persisted.ts", "export const persisted = 42;\\n", "utf-8");
""",
        encoding="utf-8",
    )

    async with (
        installed_environment({"zx": f"npm:zx@{ZX_VERSION}"}, install_path=isolated_project_cwd) as env,
        Runtime(
            env=env,
        ) as runtime,
    ):
        await runtime(Command("zx"))("persist.mjs")

    assert await AsyncPath(isolated_project_cwd / "persisted.ts").is_file()

    source = 'import { persisted } from "./persisted.ts"; export default () => persisted;'
    async with Environment(path=isolated_project_cwd) as env, Runtime(env=env) as runtime:
        assert await runtime(Script(source))() == 42

    assert sorted([entry.name async for entry in AsyncPath(isolated_project_cwd).iterdir()]) == [
        "deno.json",
        "deno.lock",
        "deno_dir",
        "node_modules",
        "persist.mjs",
        "persisted.ts",
    ]


async def test_environment_materializes_node_modules_symlink_at_workspace_during_install(
    isolated_project_cwd: Path,
) -> None:
    process_root = isolated_project_cwd.parent / "process"
    node_modules = process_root / "node_modules"

    async with Environment({"semver": "7.7.2"}) as env:
        await env.install()
        assert node_modules.is_symlink()
        assert node_modules.exists()

    assert not node_modules.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Vite build loads Rollup's native Node-API addon")
async def test_vite_nested_path_installs_persisted_node_modules(
    isolated_project_cwd: Path,
) -> None:
    frontend = isolated_project_cwd / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        (
            '<!doctype html><html><body><div id="root"></div>'
            '<script type="module" src="/main.jsx"></script></body></html>\n'
        ),
        encoding="utf-8",
    )
    (frontend / "main.jsx").write_text(
        (
            'import React from "react";\n'
            'export default function App() { return React.createElement("p", null, "belgie"); }\n'
        ),
        encoding="utf-8",
    )
    (frontend / "vite.config.js").write_text(
        """
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
});
""",
        encoding="utf-8",
    )

    node_modules = isolated_project_cwd / "node_modules"
    dependencies = {
        "react": REACT_VERSION,
        "vite": VITE_VERSION,
        "@vitejs/plugin-react": VITE_REACT_PLUGIN_VERSION,
    }
    async with Environment(dependencies, path=isolated_project_cwd) as env:
        await env.install()
        assert node_modules.is_dir()
        assert not node_modules.is_symlink()
        async with Runtime(env=env) as runtime:
            await runtime(Command("vite", cwd="frontend"))("build", "--outDir", "output")

    assert (frontend / "output" / "index.html").is_file()
    assert node_modules.is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="Vite build loads Rollup's native Node-API addon")
async def test_vite_command_refreshes_scoped_local_file_dependency_for_nested_cwd(
    isolated_project_cwd: Path,
    local_vite_plugin_package,
) -> None:
    packages = isolated_project_cwd / "packages"
    local_vite_plugin_package(packages)
    frontend = isolated_project_cwd / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<!doctype html><html><body><script type="module" src="/main.js"></script></body></html>\n',
        encoding="utf-8",
    )
    (frontend / "main.js").write_text('document.body.dataset.ready = "true";\n', encoding="utf-8")
    (frontend / "vite.config.js").write_text(
        """
import localPlugin from "@acme/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [localPlugin()],
});
""",
        encoding="utf-8",
    )

    installed_plugin = isolated_project_cwd / "node_modules" / "@acme" / "vite"
    dependencies = {
        "@acme/vite": "file:./packages/@acme/vite",
        "vite": VITE_VERSION,
    }
    async with Environment(dependencies, path=isolated_project_cwd) as env:
        await env.install()
        assert installed_plugin.is_dir()
        shutil.rmtree(installed_plugin)
        assert not installed_plugin.exists()
        async with Runtime(env=env) as runtime:
            await runtime(Command("vite", cwd="frontend"))("build", "--outDir", "output")

    assert installed_plugin.is_dir()
    assert (frontend / "output" / "index.html").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="Vite build loads Rollup's native Node-API addon")
async def test_vite_build_forwards_arguments_and_uses_nested_cwd_and_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BELGIE_COMMAND_TEST", "original")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")
    (frontend / "vite.config.js").write_text(
        """
if (process.env.BELGIE_COMMAND_TEST !== "set") {
  throw new Error("command environment was not applied");
}
export default {};
""",
        encoding="utf-8",
    )

    command = Command("vite", cwd="frontend", env={"BELGIE_COMMAND_TEST": "set"})
    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        await runtime(command)("build", "--outDir", "output")

    assert (frontend / "output" / "index.html").is_file()
    assert environ["BELGIE_COMMAND_TEST"] == "original"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific command cwd normalization")
async def test_windows_vite_build_reaches_rollup_with_normalized_cwd_before_node_api_host_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")
    capfd.readouterr()

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        with pytest.raises(BelgieRuntimeError):
            await runtime(Command("vite"))("build")

    stderr = capfd.readouterr().err.replace("\\", "/")
    assert "Node-API symbol" in stderr
    assert "parseAsync is not a function" in stderr
    assert "/?/C:/" not in stderr


async def test_missing_command_and_nonzero_exit_raise_runtime_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        with pytest.raises(BelgieRuntimeError):
            await runtime(Command("missing"))()
        with pytest.raises(BelgieRuntimeError, match=r"exit|status|failed"):
            await runtime(Command("vite"))("build", "--config", "missing.config.js")


async def test_command_arguments_must_be_strings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        command = runtime(Command("vite"))
        with pytest.raises(TypeError, match="argument 0 must be str"):
            command(cast("Any", 42))


async def test_cancelled_command_skips_exit_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    started = tmp_path / "started.txt"
    process_exit = tmp_path / "process-exit.txt"
    unload = tmp_path / "unload.txt"
    started_path = dumps(str(started))
    process_exit_path = dumps(str(process_exit))
    unload_path = dumps(str(unload))
    (tmp_path / "cancel.mjs").write_text(
        f"""
import {{ writeFileSync }} from "node:fs";

process.on(
  "exit",
  () => writeFileSync({process_exit_path}, "exit", "utf-8"),
);
globalThis.addEventListener(
  "unload",
  () => writeFileSync({unload_path}, "unload", "utf-8"),
);
writeFileSync({started_path}, "started", "utf-8");
setInterval(() => {{}}, 1000);
""",
        encoding="utf-8",
    )

    async with installed_environment({"zx": f"npm:zx@{ZX_VERSION}"}) as env, Runtime(env=env) as runtime:
        task = asyncio.create_task(runtime(Command("zx"))("cancel.mjs"))
        for _ in range(50):
            if started.is_file():
                break
            await asyncio.sleep(0.05)
        assert started.is_file()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert not process_exit.exists()
    assert not unload.exists()


async def test_cancelling_vite_dev_stops_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    free_port: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        task = asyncio.create_task(
            runtime(Command("vite"))("dev", "--host", "127.0.0.1", "--port", str(free_port)),
        )
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_runtime_exit_cancels_running_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    free_port: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")

    async with installed_environment({"vite": VITE_VERSION}) as env:
        runtime = Runtime(env=env)
        active = await runtime.__aenter__()
        task = asyncio.create_task(
            active(Command("vite"))("dev", "--host", "127.0.0.1", "--port", str(free_port)),
        )
        await asyncio.sleep(0.5)
        await runtime.__aexit__(None, None, None)

    with pytest.raises((BelgieRuntimeError, asyncio.CancelledError)):
        await task


async def test_command_waiting_for_global_context_is_cancellable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    free_port: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        server = asyncio.create_task(
            runtime(Command("vite"))("dev", "--host", "127.0.0.1", "--port", str(free_port)),
        )
        await asyncio.sleep(0.25)
        waiting = asyncio.create_task(runtime(Command("vite"))("--version"))
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        server.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server


async def test_concurrent_script_and_command_with_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BELGIE_PROBE", "baseline")

    for directory, expected in (("baseline", "baseline"), ("override", "command")):
        root = tmp_path / directory
        root.mkdir()
        (root / "probe.mjs").write_text(
            f"""
import {{ mkdirSync, writeFileSync }} from "node:fs";

if (process.env.BELGIE_PROBE !== "{expected}") {{
  throw new Error("saw " + process.env.BELGIE_PROBE);
}}
mkdirSync("output", {{ recursive: true }});
writeFileSync("output/probe.txt", process.cwd() + "\\n", "utf-8");
""",
            encoding="utf-8",
        )

    script = Script("export default async () => 'ok';")
    baseline_command = Command("zx", cwd="baseline")
    override_command = Command("zx", cwd="override", env={"BELGIE_PROBE": "command"})

    async with installed_environment({"zx": f"npm:zx@{ZX_VERSION}"}) as env, Runtime(env=env) as runtime:
        script_result, _baseline_result, _override_result = await asyncio.gather(
            runtime(script)(),
            runtime(baseline_command)("probe.mjs"),
            runtime(override_command)("probe.mjs"),
        )
        assert script_result == "ok"

    assert environ["BELGIE_PROBE"] == "baseline"
    assert (tmp_path / "baseline" / "output" / "probe.txt").read_text(encoding="utf-8") == (
        str(tmp_path / "baseline") + "\n"
    )
    assert (tmp_path / "override" / "output" / "probe.txt").read_text(encoding="utf-8") == (
        str(tmp_path / "override") + "\n"
    )


async def test_concurrent_script_and_command_reversed_gather_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BELGIE_PROBE", "baseline")

    for directory, expected in (("baseline", "baseline"), ("override", "command")):
        root = tmp_path / directory
        root.mkdir()
        (root / "probe.mjs").write_text(
            f"""
import {{ mkdirSync, writeFileSync }} from "node:fs";

if (process.env.BELGIE_PROBE !== "{expected}") {{
  throw new Error("saw " + process.env.BELGIE_PROBE);
}}
mkdirSync("output", {{ recursive: true }});
writeFileSync("output/probe.txt", process.cwd() + "\\n", "utf-8");
""",
            encoding="utf-8",
        )

    script = Script("export default async () => 'ok';")
    baseline_command = Command("zx", cwd="baseline")
    override_command = Command("zx", cwd="override", env={"BELGIE_PROBE": "command"})

    async with installed_environment({"zx": f"npm:zx@{ZX_VERSION}"}) as env, Runtime(env=env) as runtime:
        _baseline_result, _override_result, script_result = await asyncio.gather(
            runtime(baseline_command)("probe.mjs"),
            runtime(override_command)("probe.mjs"),
            runtime(script)(),
        )
        assert script_result == "ok"

    assert environ["BELGIE_PROBE"] == "baseline"
    assert (tmp_path / "baseline" / "output" / "probe.txt").read_text(encoding="utf-8") == (
        str(tmp_path / "baseline") + "\n"
    )
    assert (tmp_path / "override" / "output" / "probe.txt").read_text(encoding="utf-8") == (
        str(tmp_path / "override") + "\n"
    )
