from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text("export default function App() { return null; }\n")
    (views / "dist").mkdir(parents=True, exist_ok=True)
    return views


@pytest.fixture
def write_script(tmp_path: Path):
    def write_script_file(source: str, name: str = "main.js") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8", newline="\n")
        return path

    return write_script_file


@pytest.fixture
def default_export_source() -> str:
    return """
export default function run(input) {
  return { ok: true, input };
}
"""


@pytest.fixture
def named_run_source() -> str:
    return """
export function run(input) {
  return { ok: true, input };
}
"""


def write_manifest(views: Path, *, assets_dir: str = "dist", manifest_out_dir: str | None = None) -> None:
    out_dir = manifest_out_dir or assets_dir
    manifest: dict[str, Any] = {
        "outDir": out_dir,
        "root": str(views),
        "widgets": {
            "hello": {
                "client": f"{out_dir}/hello/client.js",
                "css": [f"{out_dir}/hello/client.css"],
                "entry": "hello/widget.tsx",
            },
        },
    }

    path = views / assets_dir / "belgie-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
