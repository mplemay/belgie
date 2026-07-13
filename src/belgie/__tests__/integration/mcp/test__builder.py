from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest
from mcp.server.mcpserver.resources import TextResource

from belgie import Command, Environment, Runtime, Script
from belgie.errors import BelgieJavaScriptError, BelgieRuntimeError
from belgie.mcp import BelgieExtension
from belgie.mcp._builder import build_widget_script, load_widget_manifest

pytestmark = pytest.mark.integration

SKIP_WIN32_VITE_NATIVE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Vite build loads Rollup's native Node-API addon",
)

VITE_VERSION = "8.1.3"
REACT_VERSION = "^19"
VITE_REACT_PLUGIN_VERSION = "^4"
TAILWIND_VERSION = "4.3.0"
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
    (widget_dir / "global.css").write_text(
        '.message { color: rebeccapurple; }\n.message::after { content: "</style>"; }\n',
        encoding="utf-8",
    )
    (widget_dir / "index.tsx").write_text(
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
  return (
    <Widget metadata={{ name: "Hello", version: "1.0.0" }}>
      <Hello />
    </Widget>
  );
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


@SKIP_WIN32_VITE_NATIVE
def test_vite_plugin_build_rejects_missing_default_export(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project)
    widget_dir = project / "src" / "widgets" / "broken"
    widget_dir.mkdir(parents=True)
    (widget_dir / "index.tsx").write_text(
        "export function Broken() {\n  return <p>broken</p>;\n}\n",
        encoding="utf-8",
    )

    with pytest.raises(BelgieRuntimeError, match=r"exit|status|failed"):
        build_widgets(project)

    stderr = capfd.readouterr().err
    assert "missing a default export" in stderr


@SKIP_WIN32_VITE_NATIVE
def test_embedded_widget_builds_inline_html_without_writing_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project)
    write_hello_widget(project)
    before = {path.relative_to(project) for path in project.rglob("*")}

    html = build_widget_script(
        Script.from_file(project / "src" / "widgets" / "hello" / "index.tsx"),
        project_path=project,
    )

    after = {path.relative_to(project) for path in project.rglob("*")}
    assert after == before
    assert "<!doctype html>" in html.lower()
    assert '<script type="module">' in html
    assert "<style>" in html
    assert "#639" in html
    assert "Hello from Belgie" in html
    assert "<\\/script>" in html
    assert "<\\/style>" in html
    assert html.count("</script>") == 1
    assert html.count("</style>") == 1
    assert '<script type="module" src=' not in html
    assert '<link rel="stylesheet"' not in html
    assert not (project / "dist").exists()


@SKIP_WIN32_VITE_NATIVE
def test_embedded_widget_inherits_safe_vite_config(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    (project / "src").mkdir()
    (project / "src" / "message.ts").write_text('export default "from alias";\n', encoding="utf-8")
    (project / "src" / "lazy.ts").write_text('export const value = "lazy-value";\n', encoding="utf-8")
    (project / "src" / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"embedded-asset" * 1024)
    config_dir = project / "configs"
    config_dir.mkdir()
    (config_dir / "widget.ts").write_text(
        """
import { resolve } from "node:path";
import { belgie } from "@belgie/mcp/vite";
import { defineConfig } from "vite";

export default defineConfig({
  define: { __BUILD_LABEL__: JSON.stringify("from define") },
  plugins: [
    belgie(),
    { name: "override-output", config: () => ({ build: { outDir: "plugin-output", write: true } }) },
  ],
  resolve: { alias: { "@message": resolve(import.meta.dirname, "../src/message.ts") } },
  build: { outDir: "should-not-exist", write: true },
});
""".lstrip(),
        encoding="utf-8",
    )
    widget_path = project / "src" / "demo.tsx"
    widget_path.write_text(
        """
import { Widget } from "@belgie/mcp";
import message from "@message";
import imageUrl from "./image.png";

declare const __BUILD_LABEL__: string;

export default function Demo() {
  return (
    <Widget metadata={{ name: "Demo", version: "1.0.0" }}>
      <button onClick={() => void import("./lazy.ts")}>{message} {__BUILD_LABEL__}</button>
      <img src={imageUrl} alt="Embedded" />
    </Widget>
  );
}
""".lstrip(),
        encoding="utf-8",
    )

    html = build_widget_script(
        Script.from_file(widget_path),
        project_path=project,
        vite_config=Path("configs/widget.ts"),
    )

    assert "from alias" in html
    assert "from define" in html
    assert "lazy-value" in html
    assert "data:image/png;base64," in html
    assert not (project / "should-not-exist").exists()
    assert not (project / "plugin-output").exists()


@SKIP_WIN32_VITE_NATIVE
def test_embedded_widget_denies_plugin_filesystem_writes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    (project / "vite.config.ts").write_text(
        """
import { writeFileSync } from "node:fs";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [{
    name: "attempt-write",
    buildStart() {
      writeFileSync(new URL("./forbidden.txt", import.meta.url), "forbidden");
    },
  }],
});
""".lstrip(),
        encoding="utf-8",
    )
    script = Script("export default function Demo() { return <main>demo</main>; }")

    with pytest.raises(BelgieJavaScriptError, match=r"Requires.*(write|write access)"):
        build_widget_script(script, project_path=project)

    assert not (project / "forbidden.txt").exists()


@SKIP_WIN32_VITE_NATIVE
def test_embedded_widget_denies_ffi_outside_node_modules(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    outside_lib = tmp_path / "outside.dylib"
    outside_lib.write_bytes(b"not-a-real-dylib")
    (project / "vite.config.ts").write_text(
        f"""
import {{ defineConfig }} from "vite";

export default defineConfig({{
  plugins: [{{
    name: "attempt-outside-ffi",
    buildStart() {{
      Deno.dlopen({str(outside_lib.resolve())!r}, {{}});
    }},
  }}],
}});
""".lstrip(),
        encoding="utf-8",
    )
    script = Script("export default function Demo() { return <main>demo</main>; }")

    with pytest.raises(BelgieJavaScriptError, match=r"Requires.*(ffi|ffi access)|dlopen|NotCapable"):
        build_widget_script(script, project_path=project)


@SKIP_WIN32_VITE_NATIVE
def test_belgie_extension_registers_embedded_script_widget(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    write_vite_config(project)
    write_hello_widget(project)
    before = {path.relative_to(project) for path in project.rglob("*")}
    widget = Script.from_file(project / "src" / "widgets" / "hello" / "index.tsx")
    extension = BelgieExtension(project=project)

    @extension.tool(widget=widget, name="hello")
    def hello() -> str:
        return "ok"

    after = {path.relative_to(project) for path in project.rglob("*")}
    assert after == before
    assert not (project / "dist").exists()
    resources = extension.resources()
    assert len(resources) == 1
    resource = resources[0].resource
    assert isinstance(resource, TextResource)
    assert "Hello from Belgie" in resource.text
    assert resource.uri == "ui://hello"


@SKIP_WIN32_VITE_NATIVE
def test_embedded_widget_uses_tailwind_plugin_from_vite_config(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    src = project / "src"
    src.mkdir()
    (src / "styles.css").write_text('@import "tailwindcss";\n', encoding="utf-8")
    widget_path = src / "demo.tsx"
    widget_path.write_text(
        """
import "./styles.css";

export default function Demo() {
  return <p className="font-bold text-red-500">Tailwind</p>;
}
""".lstrip(),
        encoding="utf-8",
    )
    (project / "vite.config.ts").write_text(
        """
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({ plugins: [tailwindcss()] });
""".lstrip(),
        encoding="utf-8",
    )

    html = build_widget_script(Script.from_file(widget_path), project_path=project)

    assert ".font-bold" in html
    assert ".text-red-500" in html
    assert '<link rel="stylesheet"' not in html


@SKIP_WIN32_VITE_NATIVE
def test_embedded_widget_rejects_plugin_emitted_assets(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_widget_project(project)
    (project / "vite.config.ts").write_text(
        """
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [{
    name: "emit-asset",
    buildStart() {
      this.emitFile({ type: "asset", name: "extra.txt", source: "extra" });
    },
  }],
});
""".lstrip(),
        encoding="utf-8",
    )
    script = Script("export default function Demo() { return <main>demo</main>; }")

    with pytest.raises(BelgieJavaScriptError, match="non-CSS assets"):
        build_widget_script(script, project_path=project)
