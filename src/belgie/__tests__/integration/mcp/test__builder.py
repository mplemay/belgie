from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path

import pytest

from belgie import Environment
from belgie.mcp._builder import build_widget

pytestmark = pytest.mark.integration


VITE_VERSION = "6.1.0"
REACT_VERSION = "^19"
VITE_REACT_PLUGIN_VERSION = "^4"


def widget_dependencies() -> dict[str, str]:
    with as_file(files("belgie.mcp._widget_package")) as widget_package_path:
        return {
            "@belgie/widget": f"file:{widget_package_path.resolve().as_posix()}",
            "@vitejs/plugin-react": f"npm:@vitejs/plugin-react@{VITE_REACT_PLUGIN_VERSION}",
            "react": f"npm:react@{REACT_VERSION}",
            "react-dom": f"npm:react-dom@{REACT_VERSION}",
            "react-dom/client": f"npm:react-dom@{REACT_VERSION}/client",
            "vite": f"npm:vite@{VITE_VERSION}",
            "vite-plugin-singlefile": "npm:vite-plugin-singlefile@^2",
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


def test_build_widget_html_returns_inline_html_document(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)

    root = tmp_path / "widgets"
    widget_dir = root / "hello"
    widget_dir.mkdir(parents=True)
    (widget_dir / "global.css").write_text(".message { color: rebeccapurple; }\n", encoding="utf-8")
    (widget_dir / "widget.tsx").write_text(
        """
import { render } from "@belgie/widget";
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

    result = build_widget(root=root, path=Path("hello/widget.tsx"), project_path=project)
    html = result.html

    assert "<!doctype html>" in html
    assert '<script type="module"' in html
    assert "<style" in html
    assert "Hello from Belgie" in html
    assert 'src="/assets/' not in html
    assert 'href="/assets/' not in html
    assert not (root / "dist").exists()
    assert not (root / "node_modules").exists()
    assert (project / "deno.lock").is_file()
    assert result.manifest.package_name == "@belgie/widget"
    assert result.manifest.package_version == "0.0.0"


@SKIP_WIN32_VITE_NATIVE
def test_build_widget_applies_render_plugins(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)

    root = tmp_path / "widgets"
    widget_dir = root / "with-plugin"
    widget_dir.mkdir(parents=True)
    (widget_dir / "widget.tsx").write_text(
        """
import { render } from "@belgie/widget";
import type { Plugin } from "vite";

function markerPlugin(): Plugin {
  return {
    name: "belgie-test-marker",
    transformIndexHtml(html) {
      return html.replace(
        "</head>",
        '<style id="belgie-plugin-marker">.plugin-marker{color:tomato}</style></head>',
      );
    },
  };
}

function App() {
  return <p className="plugin-marker">Plugin widget</p>;
}

export default function widget() {
  return render({
    plugins: [markerPlugin()],
    metadata: { title: "Plugin" },
    widget: <App />,
  });
}
""".lstrip(),
        encoding="utf-8",
    )

    result = build_widget(root=root, path=Path("with-plugin/widget.tsx"), project_path=project)
    html = result.html

    assert 'id="belgie-plugin-marker"' in html
    assert ".plugin-marker{color:tomato}" in html
    assert "Plugin widget" in html
    assert 'src="/assets/' not in html
    assert not (root / "dist").exists()
    assert not (project / "vite.config.ts").exists()
    assert not (project / "vite.config.js").exists()


@SKIP_WIN32_VITE_NATIVE
def test_build_widget_applies_render_plugins_from_async_default(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)

    root = tmp_path / "widgets"
    widget_dir = root / "with-async-plugin"
    widget_dir.mkdir(parents=True)
    (widget_dir / "widget.tsx").write_text(
        """
import { render } from "@belgie/widget";
import type { Plugin } from "vite";

function markerPlugin(): Plugin {
  return {
    name: "belgie-test-marker",
    transformIndexHtml(html) {
      return html.replace(
        "</head>",
        '<style id="belgie-plugin-marker">.plugin-marker{color:tomato}</style></head>',
      );
    },
  };
}

function App() {
  return <p className="plugin-marker">Async plugin widget</p>;
}

export default async function widget() {
  return render({
    plugins: [markerPlugin()],
    metadata: { title: "Async Plugin" },
    widget: <App />,
  });
}
""".lstrip(),
        encoding="utf-8",
    )

    result = build_widget(root=root, path=Path("with-async-plugin/widget.tsx"), project_path=project)
    html = result.html

    assert 'id="belgie-plugin-marker"' in html
    assert ".plugin-marker{color:tomato}" in html
    assert "Async plugin widget" in html
    assert 'src="/assets/' not in html
    assert not (root / "dist").exists()
    assert not (project / "vite.config.ts").exists()
    assert not (project / "vite.config.js").exists()
