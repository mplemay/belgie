from importlib.resources import as_file, files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Environment, Runtime, Script

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
        dependencies = {"@belgie/widget": f"file:{widget_package_path.as_posix()}"}
        build_script = widget_package_path / "src" / "build.ts"
        with Environment(dependencies, path=project_path) as env:
            env.install()
            with Runtime(env=env) as runtime:
                html = runtime(Script.from_file(build_script))(str(project_path), str(widget_path))
    if not isinstance(html, str):
        msg = "Belgie widget builder must return an HTML string"
        raise TypeError(msg)
    return html
