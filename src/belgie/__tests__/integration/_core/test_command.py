from __future__ import annotations

import asyncio
import shutil
import sys
from json import dumps
from os import environ
from typing import TYPE_CHECKING, Any, cast

import pytest

from belgie import Command, Environment, Runtime, Script
from belgie.__tests__.helpers.local_package import write_local_package_with_bin
from belgie.__tests__.integration._core.conftest import (
    REACT_VERSION,
    SEMVER_VERSION,
    VITE_REACT_PLUGIN_VERSION,
    VITE_VERSION,
    ZX_VERSION,
    installed_environment,
)
from belgie.errors import BelgieRuntimeError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

SKIP_WIN32_VITE_NATIVE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Vite build loads Rollup's native Node-API addon",
)


def test_environment_runtime_keeps_all_script_and_command_workers_snapshot_backed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    with Environment({"semver": SEMVER_VERSION}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script("export default () => 41"))() == 41
            assert runtime(Script("export default () => 42"))() == 42
            assert runtime(Command("semver"))("--help") is None
            assert runtime(Script("export default async () => 43"))() == 43

    assert list(tmp_path.iterdir()) == []


def test_environment_runtime_runs_local_file_package_script_and_command(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    write_local_package_with_bin(tmp_path, bin_name="local-pkg")

    source = 'import { answer } from "local-pkg"; export default () => answer;'
    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == 42
            assert runtime(Command("local-pkg"))() is None

    assert (tmp_path / "local-command.txt").read_text(encoding="utf-8") == "ok\n"


def test_environment_runtime_resolves_local_file_package_by_bin_name(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    write_local_package_with_bin(tmp_path, bin_name="local-command")

    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Command("local-command"))() is None

    assert (tmp_path / "local-command.txt").read_text(encoding="utf-8") == "ok\n"


def test_command_forks_concurrent_node_compatible_children_without_external_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    package = write_local_package_with_bin(
        tmp_path,
        bin_name="fork-probe",
        bin_script="""
import { fork } from "node:child_process";
import { writeFile } from "node:fs/promises";

const runChild = (id) => new Promise((resolve, reject) => {
  const child = fork(new URL("./child.js", import.meta.url), [String(id)]);
  let receivedMessage = false;
  child.once("error", reject);
  child.once("message", (message) => {
    receivedMessage = true;
    if (message !== id) {
      reject(new Error(`Unexpected worker response: ${message}`));
      return;
    }
    child.send("ack");
    resolve();
  });
  child.once("exit", (code) => {
    if (!receivedMessage) {
      reject(new Error(`Worker exited before responding with code ${code}`));
    }
  });
});

await Promise.all(Array.from({ length: 4 }, (_, id) => runChild(id)));
await writeFile("fork-probe.txt", "ok\\n");
""",
    )
    (package / "child.js").write_text(
        """
const id = Number(process.argv[2]);
const keepAlive = setInterval(() => {}, 1 << 30);
const failSafe = setTimeout(() => {
  clearInterval(keepAlive);
  process.exit(1);
}, 5000);
const stop = () => {
  clearTimeout(failSafe);
  clearInterval(keepAlive);
};
process.once("message", () => {
  stop();
  process.disconnect();
});
if (!process.send?.(id)) {
  stop();
  process.exit(1);
}
""",
        encoding="utf-8",
    )

    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        env.install()
        monkeypatch.setenv("PATH", "")
        with Runtime(env=env) as runtime:
            assert runtime(Command("fork-probe"))() is None

    assert (tmp_path / "fork-probe.txt").read_text(encoding="utf-8") == "ok\n"


def test_command_scopes_module_package_type_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    internal_key = "BELGIE_INTERNAL_PACKAGE_TYPE"
    monkeypatch.setenv(internal_key, "commonjs")
    write_local_package_with_bin(
        tmp_path,
        bin_name="module-probe",
        bin_script=(
            'import { writeFileSync } from "node:fs"; '
            f'writeFileSync("module-mode.txt", process.env.{internal_key} ?? "missing");\n'
        ),
    )

    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            runtime(Command("module-probe", module=True))()
            assert (tmp_path / "module-mode.txt").read_text(encoding="utf-8") == "module"
            assert environ[internal_key] == "commonjs"

            runtime(Command("module-probe"))()
            assert (tmp_path / "module-mode.txt").read_text(encoding="utf-8") == "missing"

    assert environ[internal_key] == "commonjs"


@pytest.mark.parametrize(
    ("command_spec", "clear_path"),
    [
        ("vite", True),
        (f"npm:vite@{VITE_VERSION}/vite", False),
    ],
    ids=["dependency_alias", "explicit_npm"],
)
async def test_runs_vite_command_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command_spec: str,
    *,
    clear_path: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    if clear_path:
        monkeypatch.setenv("PATH", "")

    async with installed_environment({"vite": VITE_VERSION}) as env, Runtime(env=env) as runtime:
        result = await runtime(Command(command_spec))("--version")

    assert result is None


async def test_runs_command_from_isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    async with installed_environment({"semver": SEMVER_VERSION}) as env, Runtime(env=env) as runtime:
        await runtime(Command("semver"))("--help")


async def test_relative_deno_dir_reuses_cache_for_nested_command_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DENO_DIR", "./.deno_cache")
    (tmp_path / "subdir").mkdir()

    async with installed_environment({"semver": SEMVER_VERSION}) as env, Runtime(env=env) as runtime:
        await runtime(Command("semver", cwd="subdir"))("--help")

    assert (tmp_path / ".deno_cache").is_dir()
    assert not (tmp_path / "subdir" / ".deno_cache").exists()


@SKIP_WIN32_VITE_NATIVE
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


@SKIP_WIN32_VITE_NATIVE
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


@SKIP_WIN32_VITE_NATIVE
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
