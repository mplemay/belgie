import shutil
from importlib.resources import as_file, files
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Command, Environment, Runtime

WIDGET_PATH_OUTSIDE_ROOT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension root"
COPY_IGNORE_PATTERNS: Final[tuple[str, ...]] = ("node_modules", "dist", ".git")
BUILD_DEPENDENCIES: Final[dict[str, str]] = {
    "@modelcontextprotocol/ext-apps": "latest",
    "@modelcontextprotocol/sdk": "latest",
    "@vitejs/plugin-react": "^4",
    "react": "^19",
    "react-dom": "^19",
    "vite": "6.1.0",
    "vite-plugin-singlefile": "^2",
}
INDEX_HTML: Final[str] = (
    '<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root"></div>'
    '<script type="module" src="/src/main.tsx"></script></body></html>\n'
)
VITE_CONFIG_JS: Final[str] = """
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: { outDir: "dist", emptyOutDir: true },
});
""".lstrip()


def build_widget_html(*, root: Path, path: Path) -> str:
    root_path = root.resolve(strict=True)
    widget_path = (root_path / path).resolve(strict=True)
    try:
        relative_widget_path = widget_path.relative_to(root_path)
    except ValueError as error:
        raise ValueError(WIDGET_PATH_OUTSIDE_ROOT_ERROR) from error

    with (
        as_file(files("belgie.mcp._widget_package")) as widget_package_path,
        # Vite's CLI fails to resolve transitive imports from the default system temp root.
        TemporaryDirectory(prefix="belgie-mcp-", dir=root_path.parent) as temp_dir,
    ):
        project_path = Path(temp_dir)
        shutil.copytree(
            root_path,
            project_path / "source",
            ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS),
        )
        _write_build_project(
            project_path=project_path,
            widget_import=f"../source/{relative_widget_path.as_posix()}",
        )
        dependencies = {
            **BUILD_DEPENDENCIES,
            "@belgie/widget": f"file:{widget_package_path.as_posix()}",
        }
        with Environment(dependencies, path=project_path) as env:
            env.install()
            with Runtime(env=env) as runtime:
                runtime(Command("vite"))("build", "--outDir", "dist")
        return (project_path / "dist" / "index.html").read_text(encoding="utf-8")


def _write_build_project(*, project_path: Path, widget_import: str) -> None:
    src_path = project_path / "src"
    src_path.mkdir(parents=True)
    (project_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (src_path / "main.tsx").write_text(
        f"import widget from {dumps(widget_import)};\n\nwidget();\n",
        encoding="utf-8",
    )
    (project_path / "vite.config.js").write_text(VITE_CONFIG_JS, encoding="utf-8")
