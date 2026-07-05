from __future__ import annotations

import json
from pathlib import Path

import pytest

from belgie import Environment, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie.errors import BelgieJavaScriptError

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
