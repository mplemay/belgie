from __future__ import annotations

import asyncio
import json
import sys
from json import loads
from os import environ
from pathlib import Path
from subprocess import CompletedProcess, run

import pytest

from belgie import Command, Environment, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie.__tests__.integration._core.conftest import (
    ROLLUP_VERSION,
    ZX_VERSION,
    installed_environment,
    rollup_native_package,
)
from belgie.errors import BelgieJavaScriptError


def run_fresh_python(source: str) -> CompletedProcess[str]:
    return run(  # noqa: S603
        [sys.executable, "-c", source],
        check=False,
        capture_output=True,
        text=True,
    )


pytestmark = pytest.mark.integration


@pytest.fixture
def write_script(tmp_path: Path):
    def write_script_file(source: str, name: str = "main.js") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return write_script_file


def test_executes_top_level_await_before_calling_run(tmp_path: Path):
    source = """
const resolved = await Promise.resolve(41);
export default function run(input) {
  return resolved + input.delta;
}
"""

    with Runtime() as runtime:
        assert runtime(Script(source))({"delta": 1}) == 42


def test_module_scope_state_persists_within_one_context(tmp_path: Path):
    source = """
let count = 0;
export default function run() {
  count += 1;
  return count;
}
"""

    with Runtime() as runtime:
        run = runtime(Script(source))
        assert run() == 1
        assert run() == 2
        assert run() == 3


def test_executes_with_runtime_options(tmp_path: Path):
    options = RuntimeOptions(max_old_generation_size_mb=64)

    with Runtime(options=options) as runtime:
        assert runtime(Script("export default () => 'configured'"))() == "configured"


def test_runtime_worker_seed_is_deterministic_with_environment(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with Environment(path=project) as env, Runtime(env=env, options=RuntimeOptions(seed=123)) as runtime:
        assert runtime(Script("export default () => 'seeded';"))() == "seeded"


def test_runtime_worker_location_is_exposed_with_environment(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with (
        Environment(path=project) as env,
        Runtime(
            env=env,
            options=RuntimeOptions(location="https://example.com/app?x=1"),
        ) as runtime,
    ):
        assert runtime(Script("export default () => globalThis.location.href;"))() == "https://example.com/app?x=1"


def test_runtime_can_disable_offscreen_canvas_with_environment(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with (
        Environment(path=project) as env,
        Runtime(env=env, options=RuntimeOptions(disable_offscreen_canvas=True)) as runtime,
    ):
        assert runtime(Script("export default () => typeof globalThis.OffscreenCanvas;"))() == "undefined"


def test_runtime_supports_css_module_imports_with_raw_imports(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "style.css").write_text("body { color: rgb(1, 2, 3); }\n", encoding="utf-8")
    main = project / "main.js"
    main.write_text(
        """
import sheet from "./style.css" with { type: "css" };

export default () => ({
  constructorName: sheet.constructor.name,
  replaceSyncType: typeof sheet.replaceSync,
});
""",
        encoding="utf-8",
    )

    with (
        Environment(path=project) as env,
        Runtime(env=env, options=RuntimeOptions(enable_raw_imports=True)) as runtime,
    ):
        assert runtime(Script.from_file(main))() == {
            "constructorName": "CSSStyleSheet",
            "replaceSyncType": "function",
        }


def test_runtime_permissions_can_deny_and_allow_read_access(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    source = f"export default () => Deno.readTextFileSync({json.dumps(str(secret))});"

    with (
        Environment(path=project) as env,
        Runtime(
            env=env,
            options=RuntimeOptions(permissions=RuntimePermissions.none()),
        ) as runtime,
        pytest.raises(BelgieJavaScriptError, match="read|NotCapable"),
    ):
        runtime(Script(source))()

    with (
        Environment(path=project) as env,
        Runtime(
            env=env,
            options=RuntimeOptions(permissions=RuntimePermissions(allow_read=[str(secret)])),
        ) as runtime,
    ):
        assert runtime(Script(source))() == "secret"


def test_package_worker_applies_memory_options_with_cli_snapshot(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with (
        Environment(path=project) as env,
        Runtime(
            env=env,
            options=RuntimeOptions(max_old_generation_size_mb=64, seed=1),
        ) as runtime,
    ):
        assert runtime(Script("export default () => 'package-memory';"))() == "package-memory"


def test_executes_script_loaded_from_file(tmp_path: Path, write_script):
    path = write_script(
        """
export default function run(input) {
  return input.name.toUpperCase();
}
""",
        "main.js",
    )

    with Runtime() as runtime:
        assert runtime(Script.from_file(path))({"name": "belgie"}) == "BELGIE"


def test_inline_script_filename_enables_tsx_media_type(tmp_path: Path) -> None:
    source = """
const React = { createElement: (type: string) => ({ type }) };
export default () => (<main />).type;
"""

    with Runtime.from_folder(tmp_path) as runtime:
        assert runtime(Script(source, filename="widget.tsx"))() == "main"


def test_inline_script_filename_sets_relative_import_base(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "message.ts").write_text('export const message = "relative";\n', encoding="utf-8")
    source = 'import { message } from "./message.ts"; export default () => message;'

    with Runtime.from_folder(tmp_path) as runtime:
        assert runtime(Script(source, filename="src/widget.ts"))() == "relative"


def test_transpiles_relative_typescript_imports_from_script_file(tmp_path: Path, write_script):
    write_script(
        """
export function double(value: number): number {
  return value * 2;
}
""",
        "lib/math.ts",
    )
    path = write_script(
        """
import { double } from "./lib/math.ts";

export default function run(input: { value: number }): number {
  return double(input.value);
}
""",
        "main.ts",
    )

    with Runtime() as runtime:
        assert runtime(Script.from_file(path))({"value": 21}) == 42


def test_passes_keyword_arguments_as_ordered_final_object(tmp_path: Path):
    source = """
export default function run(input, options) {
  return {
    input,
    optionKeys: Object.keys(options),
    options,
  };
}
"""

    with Runtime() as runtime:
        assert runtime(Script(source))({"value": 1}, z=True, a=False) == {
            "input": {"value": 1},
            "optionKeys": ["z", "a"],
            "options": {"z": True, "a": False},
        }


async def test_sync_runtime_from_folder_inside_async_coroutine(tmp_path: Path):
    (tmp_path / "value.ts").write_text("export const value = 42;\n", encoding="utf-8")
    source = """
import { value } from "./value.ts";

export default function run() {
  return value;
}
"""

    with Runtime.from_folder(tmp_path) as runtime:
        assert runtime(Script(source))() == 42


@pytest.mark.skipif(sys.platform != "linux", reason="Linux dynamic loader regression")
def test_importing_belgie_keeps_deno_host_symbols_local() -> None:
    result = run_fresh_python(
        """
import ctypes
import json

import belgie

process = ctypes.CDLL(None)
print(json.dumps({
    "napi_create_string_utf8": hasattr(process, "napi_create_string_utf8"),
    "uv_async_init": hasattr(process, "uv_async_init"),
}))
""".strip(),
    )

    assert result.returncode == 0, result.stderr
    assert loads(result.stdout) == {
        "napi_create_string_utf8": False,
        "uv_async_init": False,
    }


@pytest.mark.skipif(sys.platform == "win32", reason="uvloop is unavailable on Windows")
def test_importing_belgie_before_uvloop_can_create_event_loop() -> None:
    result = run_fresh_python(
        """
import belgie
import uvloop

loop = uvloop.new_event_loop()
loop.close()
""".strip(),
    )

    assert result.returncode == 0, result.stderr


async def test_package_script_loads_native_rollup_addon_before_command(
    isolated_project_cwd: Path,
) -> None:
    native_package = rollup_native_package()

    source = f"""
import {{ createRequire }} from "node:module";

const require = createRequire(import.meta.url);
const native = require("{native_package}");

export default function run() {{
  return typeof native.parse;
}}
"""
    async with (
        installed_environment(
            {native_package: ROLLUP_VERSION},
            install_path=isolated_project_cwd,
        ) as env,
        Runtime(env=env) as runtime,
    ):
        assert await runtime(Script(source))() == "function"


async def _assert_concurrent_script_and_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    script_first: bool,
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
        script_call = runtime(script)()
        baseline_call = runtime(baseline_command)("probe.mjs")
        override_call = runtime(override_command)("probe.mjs")
        if script_first:
            script_result, _baseline_result, _override_result = await asyncio.gather(
                script_call,
                baseline_call,
                override_call,
            )
        else:
            _baseline_result, _override_result, script_result = await asyncio.gather(
                baseline_call,
                override_call,
                script_call,
            )
        assert script_result == "ok"

    assert environ["BELGIE_PROBE"] == "baseline"
    assert (tmp_path / "baseline" / "output" / "probe.txt").read_text(encoding="utf-8") == (
        str(tmp_path / "baseline") + "\n"
    )
    assert (tmp_path / "override" / "output" / "probe.txt").read_text(encoding="utf-8") == (
        str(tmp_path / "override") + "\n"
    )


@pytest.mark.parametrize("script_first", [True, False], ids=["script_first", "commands_first"])
async def test_concurrent_script_and_command_with_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    script_first: bool,
) -> None:
    await _assert_concurrent_script_and_commands(tmp_path, monkeypatch, script_first=script_first)
