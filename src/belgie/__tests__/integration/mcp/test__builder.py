from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest

from belgie import Command, Environment, Runtime
from belgie.mcp._builder import load_widget_manifest

pytestmark = pytest.mark.integration

SKIP_WIN32_VITE_NATIVE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Vite build loads Rollup's native Node-API addon",
)

VITE_VERSION = "6.1.0"
REACT_VERSION = "^19"
VITE_REACT_PLUGIN_VERSION = "^4"
MCP_PACKAGE_PATH: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "mcp"
BASE_URL: Final[str] = "http://127.0.0.1:3001"


def widget_dependencies() -> dict[str, str]:
    return {
        "@belgie/mcp": f"file:{MCP_PACKAGE_PATH.resolve().as_posix()}",
        "@vitejs/plugin-react": f"npm:@vitejs/plugin-react@{VITE_REACT_PLUGIN_VERSION}",
        "react": f"npm:react@{REACT_VERSION}",
        "react-dom": f"npm:react-dom@{REACT_VERSION}",
        "react-dom/client": f"npm:react-dom@{REACT_VERSION}/client",
        "vite": f"npm:vite@{VITE_VERSION}",
    }


def write_project_pyproject(project: Path, dependencies: dict[str, str]) -> None:
    lines = ["[tool.belgie.dependencies]"]
    lines.extend(
        f'"{name}" = "{specifier}"' if "/" in name or name.startswith("@") else f'{name} = "{specifier}"'
        for name, specifier in dependencies.items()
    )
    (project / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def install_widget_project(project: Path) -> None:
    dependencies = widget_dependencies()
    write_project_pyproject(project, dependencies)
    with Environment(dependencies, path=project) as env:
        env.install()


def write_vite_config(project: Path) -> None:
    (project / "vite.config.ts").write_text(
        """
import { belgie } from "@belgie/mcp/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie(), react()],
});
""".lstrip(),
        encoding="utf-8",
    )


def write_hello_widget(project: Path) -> None:
    widget_dir = project / "src" / "widgets" / "hello"
    widget_dir.mkdir(parents=True)
    (widget_dir / "global.css").write_text(".message { color: rebeccapurple; }\n", encoding="utf-8")
    (widget_dir / "index.tsx").write_text(
        """
import { render } from "@belgie/mcp";
import { useState } from "react";
import "./global.css";

function App() {
  const [message] = useState("Hello from Belgie");
  return <p className="message">{message}</p>;
}

export default function widget() {
  return render({ metadata: { title: "Hello" }, widget: <App /> });
}
""".lstrip(),
        encoding="utf-8",
    )


def build_widgets(project: Path) -> None:
    dependencies = widget_dependencies()
    with (
        Environment(dependencies, path=project, lockfile=project / "deno.lock") as env,
        Runtime(env=env) as run,
    ):
        run(Command("vite", cwd=str(project)))("build")


@SKIP_WIN32_VITE_NATIVE
def test_vite_plugin_build_and_manifest_script(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project)
    write_hello_widget(project)
    build_widgets(project)

    html_path = project / "dist" / "widgets" / "hello" / "index.html"
    assert html_path.is_file()
    built_html = html_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in built_html
    assert 'src="/assets/' in built_html or 'href="/assets/' in built_html
    assert (project / "dist" / "assets").is_dir()
    assert any((project / "dist" / "assets").iterdir())

    manifest = load_widget_manifest(base_url=BASE_URL, project_path=project)
    assert manifest.base_url == BASE_URL
    assert "hello" in manifest.widgets
    html = manifest.widgets["hello"].html
    assert "<!doctype html>" in html
    assert f'src="{BASE_URL}/assets/' in html or f'href="{BASE_URL}/assets/' in html
    assert 'src="/assets/' not in html
    assert "Hello from Belgie" not in html  # source text lives in the JS chunk, not the HTML shell
