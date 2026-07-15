from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from time import monotonic
from typing import Final
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from mcp.server.mcpserver.resources import TextResource

from belgie import Command, Environment, Runtime
from belgie.errors import BelgieRuntimeError
from belgie.mcp import BelgieExtension
from belgie.mcp._manifest import load_widget_manifest

pytestmark = pytest.mark.integration

SKIP_WIN32_VITE_NATIVE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Vite build loads Rollup's native Node-API addon",
)

VITE_VERSION: Final[str] = "8.1.3"
REACT_VERSION: Final[str] = "^19"
VITE_REACT_PLUGIN_VERSION: Final[str] = "^6"
TAILWIND_VERSION: Final[str] = "4.3.0"
MCP_PACKAGE_PATH: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "mcp"
BASE_URL: Final[str] = "http://127.0.0.1:3001"


def widget_dependencies() -> dict[str, str]:
    return {
        "@belgie/mcp": f"file:{MCP_PACKAGE_PATH.resolve().as_posix()}",
        "@modelcontextprotocol/ext-apps": "npm:@modelcontextprotocol/ext-apps@latest",
        "@tailwindcss/vite": f"npm:@tailwindcss/vite@{TAILWIND_VERSION}",
        "@vitejs/plugin-react": f"npm:@vitejs/plugin-react@{VITE_REACT_PLUGIN_VERSION}",
        "react": f"npm:react@{REACT_VERSION}",
        "react-dom": f"npm:react-dom@{REACT_VERSION}",
        "react-dom/client": f"npm:react-dom@{REACT_VERSION}/client",
        "tailwindcss": f"npm:tailwindcss@{TAILWIND_VERSION}",
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
    (project / "package.json").write_text(
        '{"name": "belgie-widget-test", "private": true}\n',
        encoding="utf-8",
    )
    with Environment(dependencies, path=project) as env:
        env.install()


def write_vite_config(project: Path, *, tailwind: bool = False) -> None:
    tailwind_import = 'import tailwindcss from "@tailwindcss/vite";\n' if tailwind else ""
    plugins = "[belgie(), react(), tailwindcss()]" if tailwind else "[belgie(), react()]"
    (project / "vite.config.ts").write_text(
        f"""
import {{ resolve }} from "node:path";
import {{ belgie }} from "@belgie/mcp/vite";
import react from "@vitejs/plugin-react";
{tailwind_import}import {{ defineConfig }} from "vite";

export default defineConfig({{
  define: {{ __BUILD_LABEL__: JSON.stringify("from define") }},
  plugins: {plugins},
  resolve: {{ alias: {{ "@message": resolve(import.meta.dirname, "src/message.ts") }} }},
}});
""".lstrip(),
        encoding="utf-8",
    )


def write_widget(project: Path, name: str, source: str, *, css: str | None = None) -> Path:
    widget_dir = project / "src" / "widgets" / name
    widget_dir.mkdir(parents=True)
    if css is not None:
        (widget_dir / "global.css").write_text(css, encoding="utf-8")
    widget = widget_dir / "widget.tsx"
    widget.write_text(source, encoding="utf-8")
    return widget


def write_hello_widget(project: Path, name: str = "hello") -> Path:
    return write_widget(
        project,
        name,
        """
import { Widget } from "@belgie/mcp";
import { useState } from "react";
import "./global.css";

function Hello() {
  const [message] = useState("Hello from Belgie");
  const marker = "</script>";
  return <p className="message" data-marker={marker}>{message}</p>;
}

export default function HelloWidget() {
  return <Widget metadata={{ name: "Hello", version: "1.0.0" }}><Hello /></Widget>;
}
""".lstrip(),
        css='.message { color: rebeccapurple; }\n.message::after { content: "</style>"; }\n',
    )


def build_widgets(project: Path) -> None:
    dependencies = widget_dependencies()
    with (
        Environment(dependencies, path=project, lockfile=project / "deno.lock") as env,
        Runtime(env=env) as run,
    ):
        run(Command("vite", cwd=str(project)))("build")


def fetch_text(url: str) -> str:
    with urlopen(url, timeout=1) as response:  # noqa: S310  # Test URL is a fixed local HTTP origin.
        return response.read().decode("utf-8")


async def wait_for_url(url: str) -> str:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        try:
            return await asyncio.to_thread(fetch_text, url)
        except URLError:
            await asyncio.sleep(0.1)
    pytest.fail(f"Vite server did not become available at {url}")


@SKIP_WIN32_VITE_NATIVE
async def test_vite_dev_serves_widget_route_before_python_registration(tmp_path: Path, free_port: int) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project)
    widget = write_hello_widget(project)
    dev_url = f"http://127.0.0.1:{free_port}"
    widget_url = f"{dev_url}/widgets/hello/index.html"

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "belgie.cli",
        "run",
        "vite",
        "--host",
        "127.0.0.1",
        "--port",
        str(free_port),
        cwd=project,
    )
    try:
        html = await wait_for_url(widget_url)
        assert "/@vite/client" in html
        assert "@react-refresh" in html
        assert "/_belgie/widget/hello" in html

        extension = BelgieExtension(project=project, dev_url=dev_url)

        @extension.tool(widget=widget, name="hello")
        def hello() -> str:
            return "ok"

        resource = extension.resources()[0].resource
        assert isinstance(resource, TextResource)
        assert f'<base href="{dev_url}/" />' in resource.text
        assert resource.meta == {
            "ui": {
                "csp": {
                    "connectDomains": [dev_url, f"ws://127.0.0.1:{free_port}"],
                    "resourceDomains": [dev_url],
                    "baseUriDomains": [dev_url],
                },
            },
        }
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
    assert not (project / "dist").exists()


@SKIP_WIN32_VITE_NATIVE
def test_vite_build_emits_standalone_html_for_each_widget(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project)
    write_hello_widget(project)
    write_hello_widget(project, "second")
    old_widget = project / "src" / "widgets" / "old" / "index.tsx"
    old_widget.parent.mkdir(parents=True)
    old_widget.write_text("export default function Old() { return <p>old</p>; }\n", encoding="utf-8")
    nested_widget = project / "src" / "widgets" / "nested" / "child" / "widget.tsx"
    nested_widget.parent.mkdir(parents=True)
    nested_widget.write_text("export default function Nested() { return <p>nested</p>; }\n", encoding="utf-8")

    build_widgets(project)

    for name in ("hello", "second"):
        html_path = project / "dist" / "widgets" / name / "index.html"
        assert html_path.is_file()
        html = html_path.read_text(encoding="utf-8")
        assert "<!doctype html>" in html.lower()
        assert '<script type="module">' in html
        assert "<style>" in html
        assert "Hello from Belgie" in html
        assert "<\\/script>" in html
        assert "<\\/style>" in html
        assert '<script type="module" src=' not in html
        assert '<link rel="stylesheet"' not in html

    assert not (project / "dist" / "assets").exists()
    assert not (project / "dist" / "widgets" / "old").exists()
    assert not (project / "dist" / "widgets" / "child").exists()
    manifest = load_widget_manifest(base_url=BASE_URL, project_path=project)
    assert set(manifest.widgets) == {"hello", "second"}
    assert manifest.widgets["hello"].html == (project / "dist" / "widgets" / "hello" / "index.html").read_text(
        encoding="utf-8",
    )


@SKIP_WIN32_VITE_NATIVE
def test_vite_build_rejects_missing_default_export(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project)
    write_widget(project, "broken", "export function Broken() { return <p>broken</p>; }\n")

    with pytest.raises(BelgieRuntimeError, match=r"exit|status|failed"):
        build_widgets(project)

    assert "missing a default export" in capfd.readouterr().err


@SKIP_WIN32_VITE_NATIVE
def test_vite_build_inherits_plugins_aliases_and_inlines_assets(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project, tailwind=True)
    src = project / "src"
    src.mkdir(exist_ok=True)
    (src / "message.ts").write_text('export default "from alias";\n', encoding="utf-8")
    (src / "lazy.ts").write_text('export const value = "lazy-value";\n', encoding="utf-8")
    (src / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"embedded-asset" * 1024)
    (src / "font.woff2").write_bytes(b"wOF2" + b"embedded-font" * 1024)
    write_widget(
        project,
        "demo",
        """
import message from "@message";
import imageUrl from "../../image.png";
import "./global.css";

declare const __BUILD_LABEL__: string;

export default function Demo() {
  return (
    <button className="font-bold text-red-500" onClick={() => void import("../../lazy.ts")}>
      {message} {__BUILD_LABEL__}<img src={imageUrl} alt="Embedded" />
    </button>
  );
}
""".lstrip(),
        css=(
            '@import "tailwindcss";\n'
            '@font-face { font-family: "Demo"; src: url("../../font.woff2") format("woff2"); }\n'
        ),
    )

    build_widgets(project)

    html = (project / "dist" / "widgets" / "demo" / "index.html").read_text(encoding="utf-8")
    assert "from alias" in html
    assert "from define" in html
    assert "lazy-value" in html
    assert "data:image/png;base64," in html
    assert "data:font/woff2;base64," in html
    assert ".font-bold" in html
    assert ".text-red-500" in html


@SKIP_WIN32_VITE_NATIVE
def test_vite_build_rejects_plugin_emitted_assets(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    (project / "vite.config.ts").write_text(
        """
import { belgie } from "@belgie/mcp/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [
    belgie(),
    react(),
    {
      name: "emit-asset",
      buildStart() {
        this.emitFile({ type: "asset", name: "extra.txt", source: "extra" });
      },
    },
  ],
});
""".lstrip(),
        encoding="utf-8",
    )
    write_hello_widget(project)

    with pytest.raises(BelgieRuntimeError, match=r"exit|status|failed"):
        build_widgets(project)

    assert "non-CSS assets" in capfd.readouterr().err
