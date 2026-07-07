from importlib.resources import as_file, files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Environment, Runtime, Script

WIDGET_PATH_OUTSIDE_ROOT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension root"
BUILD_DEPENDENCIES: Final[dict[str, str]] = {
    "@modelcontextprotocol/ext-apps": "latest",
    "@modelcontextprotocol/sdk": "latest",
    "@vitejs/plugin-react": "^4",
    "react": "^19",
    "react-dom": "^19",
    "vite": "6.1.0",
    "vite-plugin-singlefile": "^2",
}


def build_widget_html(*, root: Path, path: Path) -> str:
    root_path = root.resolve(strict=True)
    widget_path = (root_path / path).resolve(strict=True)
    try:
        relative_widget_path = widget_path.relative_to(root_path)
    except ValueError as error:
        raise ValueError(WIDGET_PATH_OUTSIDE_ROOT_ERROR) from error

    with (
        as_file(files("belgie.mcp._widget_package")) as widget_package_path,
        # Keep Vite's dependency root adjacent to the widget source tree for cross-root imports.
        TemporaryDirectory(prefix="belgie-mcp-", dir=root_path.parent) as temp_dir,
    ):
        project_path = Path(temp_dir)
        build_script = Script.from_file(widget_package_path / "run-build.ts")
        dependencies = {
            **BUILD_DEPENDENCIES,
            "@belgie/widget": f"file:{widget_package_path.as_posix()}",
        }
        with Environment(dependencies, path=project_path) as env:
            env.install()
            with Runtime(env=env) as runtime:
                return runtime(build_script)(str(project_path), str(root_path), relative_widget_path.as_posix())
