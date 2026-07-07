from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Environment, Runtime, Script

WIDGET_PATH_OUTSIDE_ROOT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension root"
INVALID_WIDGET_BUILD_DEPENDENCIES_ERROR: Final[str] = "Widget build dependencies must map strings to strings"
INVALID_WIDGET_BUILD_RESULT_ERROR: Final[str] = "Widget build result must include html and manifest data"
INVALID_WIDGET_BUILD_MANIFEST_ERROR: Final[str] = "Widget build manifest must include render package metadata"


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetRenderManifest:
    render_package_name: str
    render_package_version: str


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetBuildResult:
    html: str
    manifest: WidgetRenderManifest


def build_widget(*, root: Path, path: Path) -> WidgetBuildResult:
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
        dependencies = _load_build_dependencies(widget_package_path)
        with Environment(dependencies, path=project_path) as env:
            env.install()
            with Runtime(env=env) as runtime:
                return _parse_build_result(
                    runtime(build_script)(str(project_path), str(root_path), relative_widget_path.as_posix()),
                )


def build_widget_html(*, root: Path, path: Path) -> str:
    return build_widget(root=root, path=path).html


def _load_build_dependencies(widget_package_path: Path) -> dict[str, str]:
    with Runtime() as runtime:
        payload = runtime(Script.from_file(widget_package_path / "src" / "dependencies.ts"))()

    if not isinstance(payload, Mapping):
        raise TypeError(INVALID_WIDGET_BUILD_DEPENDENCIES_ERROR)

    dependencies: dict[str, str] = {}
    for alias, specifier in payload.items():
        if not isinstance(alias, str) or not isinstance(specifier, str):
            raise TypeError(INVALID_WIDGET_BUILD_DEPENDENCIES_ERROR)
        dependencies[alias] = specifier
    return dependencies


def _parse_build_result(payload: object) -> WidgetBuildResult:
    if not isinstance(payload, Mapping):
        raise TypeError(INVALID_WIDGET_BUILD_RESULT_ERROR)

    html = payload.get("html")
    if not isinstance(html, str):
        raise TypeError(INVALID_WIDGET_BUILD_RESULT_ERROR)

    manifest = payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise TypeError(INVALID_WIDGET_BUILD_RESULT_ERROR)

    render_package_name = manifest.get("renderPackageName")
    render_package_version = manifest.get("renderPackageVersion")
    if not isinstance(render_package_name, str) or not isinstance(render_package_version, str):
        raise TypeError(INVALID_WIDGET_BUILD_MANIFEST_ERROR)

    return WidgetBuildResult(
        html=html,
        manifest=WidgetRenderManifest(
            render_package_name=render_package_name,
            render_package_version=render_package_version,
        ),
    )
