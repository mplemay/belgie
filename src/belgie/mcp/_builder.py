from importlib.resources import as_file, files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Environment, Runtime, Script

BUILD_DEPENDENCIES: Final[dict[str, str]] = {
    "@modelcontextprotocol/ext-apps": "latest",
    "@modelcontextprotocol/sdk": "latest",
    # Vite 6.1's config loader enters vite/module-runner, which currently
    # does not resolve reliably through Belgie's local file package import map.
    "esbuild-wasm-browser": "npm:esbuild-wasm@0.24.2/esm/browser.js",
    "react": "^19",
    "react-dom": "^19",
}
BUILD_WIDGET_SCRIPT: Final[str] = """
import { buildWidgetHtml } from "@belgie/widget/src/build.ts";

export default async function build(projectRoot, widgetPath) {
  return await buildWidgetHtml(projectRoot, widgetPath);
}
"""
WIDGET_PATH_OUTSIDE_ROOT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension root"


def build_widget_html(*, root: Path, path: Path) -> str:
    root_path = root.resolve(strict=True)
    widget_path = (root_path / path).resolve(strict=True)
    try:
        widget_path.relative_to(root_path)
    except ValueError as error:
        raise ValueError(WIDGET_PATH_OUTSIDE_ROOT_ERROR) from error

    with (
        as_file(files("belgie.mcp._widget_package")) as widget_package_path,
        TemporaryDirectory(prefix="belgie-mcp-") as temp_dir,
    ):
        project_path = Path(temp_dir)
        dependencies = {
            **BUILD_DEPENDENCIES,
            "@belgie/widget": f"file:{widget_package_path.as_posix()}",
        }
        with Environment(dependencies, path=project_path) as env:
            env.install()
            with Runtime(env=env) as runtime:
                html = runtime(Script(BUILD_WIDGET_SCRIPT))(str(project_path), str(widget_path))
    if not isinstance(html, str):
        msg = "Belgie widget builder must return an HTML string"
        raise TypeError(msg)
    return html
