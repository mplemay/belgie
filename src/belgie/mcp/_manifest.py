from pathlib import Path
from re import Match, Pattern, compile as compile_pattern
from typing import Final
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, ConfigDict, Field

ASSET_URL_PATTERN: Final[Pattern[str]] = compile_pattern(
    r'\b(src|href)=["\']((?:\.?/)?assets/[^"\']+)["\']',
)
INVALID_BASE_URL_ERROR: Final[str] = "base_url must be an absolute http(s) URL, got {base_url!r}"
MISSING_WIDGET_HTML_ERROR: Final[str] = "No widget HTML found under {widgets_dir}. Run `belgie run vite build` first."


class WidgetEntry(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str
    html: str


class WidgetManifest(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    base_url: str = Field(validation_alias="baseUrl")
    widgets: dict[str, WidgetEntry]


def load_widget_manifest(*, base_url: str, project_path: Path | None = None) -> WidgetManifest:
    normalized_base_url = normalize_base_url(base_url)
    resolved_project_path = resolve_project_path(project_path)
    widgets_dir = resolved_project_path / "dist" / "widgets"
    widgets: dict[str, WidgetEntry] = {}
    if widgets_dir.is_dir():
        for widget_dir in sorted(widgets_dir.iterdir()):
            html_path = widget_dir / "index.html"
            if not widget_dir.is_dir() or not html_path.is_file():
                continue
            widgets[widget_dir.name] = WidgetEntry(
                name=widget_dir.name,
                html=absolutize_asset_urls(html_path.read_text(encoding="utf-8"), normalized_base_url),
            )
    if not widgets:
        msg = MISSING_WIDGET_HTML_ERROR.format(widgets_dir=widgets_dir)
        raise FileNotFoundError(msg)
    return WidgetManifest(base_url=normalized_base_url, widgets=widgets)


def absolutize_asset_urls(html: str, base_url: str) -> str:
    def replace(match: Match[str]) -> str:
        attribute, asset_path = match.groups()
        normalized_path = asset_path.removeprefix("./").removeprefix("/")
        return f'{attribute}="{urljoin(f"{base_url}/", normalized_path)}"'

    return ASSET_URL_PATTERN.sub(replace, html)


def normalize_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = INVALID_BASE_URL_ERROR.format(base_url=base_url)
        raise ValueError(msg)
    return base_url.rstrip("/")


def resolve_project_path(path: Path | None) -> Path:
    return (Path.cwd() if path is None else Path(path)).resolve()
