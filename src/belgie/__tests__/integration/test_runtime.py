from __future__ import annotations

import asyncio
import sys
from os import environ
from typing import TYPE_CHECKING, Any, Final, cast

import pytest

from belgie import Command, Environment, Runtime, Script
from belgie.dependencies import install
from belgie.errors import BelgieRuntimeError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

VITE_VERSION: Final[str] = "6.1.0"
ZX_VERSION: Final[str] = "8.5.5"


def install_vite(tmp_path: Path, write_belgie_pyproject) -> None:
    write_belgie_pyproject(dependencies={"vite": VITE_VERSION})
    install(cwd=tmp_path)


def install_zx(tmp_path: Path, write_belgie_pyproject) -> None:
    write_belgie_pyproject(dependencies={"zx": f"npm:zx@{ZX_VERSION}"})
    install(cwd=tmp_path)


async def test_runs_dependency_alias_without_external_node_or_deno(
    tmp_path: Path,
    write_belgie_pyproject,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)
    monkeypatch.setenv("PATH", "")

    async with Runtime.from_folder(tmp_path) as runtime:
        result = await runtime(Command("vite"))("--version")

    assert result is None


async def test_runs_explicit_npm_command_bin(
    tmp_path: Path,
    write_belgie_pyproject,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)

    async with Runtime.from_folder(tmp_path) as runtime:
        await runtime(Command(f"npm:vite@{VITE_VERSION}/vite"))("--version")


async def test_runs_command_from_isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    async with Environment({"semver": "7.7.2"}) as env, Runtime(env=env) as runtime:
        await runtime(Command("semver"))("--help")


@pytest.mark.skipif(sys.platform == "win32", reason="Vite build loads Rollup's native Node-API addon")
async def test_vite_build_forwards_arguments_and_uses_nested_cwd_and_environment(
    tmp_path: Path,
    write_belgie_pyproject,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)
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
    async with Runtime.from_folder(tmp_path) as runtime:
        await runtime(command)("build", "--outDir", "output")

    assert (frontend / "output" / "index.html").is_file()
    assert environ["BELGIE_COMMAND_TEST"] == "original"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific command cwd normalization")
async def test_windows_vite_build_reaches_rollup_with_normalized_cwd_before_node_api_host_limit(
    tmp_path: Path,
    write_belgie_pyproject,
    capfd: pytest.CaptureFixture[str],
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")
    capfd.readouterr()

    async with Runtime.from_folder(tmp_path) as runtime:
        with pytest.raises(BelgieRuntimeError):
            await runtime(Command("vite"))("build")

    stderr = capfd.readouterr().err.replace("\\", "/")
    assert "Node-API symbol" in stderr
    assert "parseAsync is not a function" in stderr
    assert "/?/C:/" not in stderr


async def test_missing_command_and_nonzero_exit_raise_runtime_errors(
    tmp_path: Path,
    write_belgie_pyproject,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)

    async with Runtime.from_folder(tmp_path) as runtime:
        with pytest.raises(BelgieRuntimeError):
            await runtime(Command("missing"))()
        with pytest.raises(BelgieRuntimeError, match=r"exit|status|failed"):
            await runtime(Command("vite"))("build", "--config", "missing.config.js")


async def test_command_arguments_must_be_strings(
    tmp_path: Path,
    write_belgie_pyproject,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)

    async with Runtime.from_folder(tmp_path) as runtime:
        command = runtime(Command("vite"))
        with pytest.raises(TypeError, match="argument 0 must be str"):
            command(cast("Any", 42))


async def test_cancelling_vite_dev_stops_command(
    tmp_path: Path,
    write_belgie_pyproject,
    free_port: int,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")

    async with Runtime.from_folder(tmp_path) as runtime:
        task = asyncio.create_task(
            runtime(Command("vite"))("dev", "--host", "127.0.0.1", "--port", str(free_port)),
        )
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_runtime_exit_cancels_running_command(
    tmp_path: Path,
    write_belgie_pyproject,
    free_port: int,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")

    runtime = Runtime.from_folder(tmp_path)
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
    write_belgie_pyproject,
    free_port: int,
) -> None:
    install_vite(tmp_path, write_belgie_pyproject)
    (tmp_path / "index.html").write_text("<main>belgie</main>\n", encoding="utf-8")

    async with Runtime.from_folder(tmp_path) as runtime:
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
    write_belgie_pyproject,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_zx(tmp_path, write_belgie_pyproject)
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

    async with Runtime.from_folder(tmp_path) as runtime:
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
