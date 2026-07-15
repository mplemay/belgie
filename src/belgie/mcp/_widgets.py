from functools import cache
from html import escape
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import urlopen

WIDGET_FILENAME: Final[str] = "widget.tsx"
WIDGET_HTML_RELATIVE_PATH: Final[tuple[str, ...]] = ("dist", "widgets")
DEV_REQUEST_TIMEOUT_SECONDS: Final[float] = 5.0
INVALID_DEV_URL_ERROR: Final[str] = "dev_url must be an absolute http(s) URL, got {dev_url!r}"
MISSING_WIDGET_ERROR: Final[str] = "Widget file does not exist: {widget}"
INVALID_WIDGET_FILE_ERROR: Final[str] = "Widget path must point to a file named widget.tsx: {widget}"
WIDGET_OUTSIDE_PROJECT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension project: {widget}"
MISSING_BUILT_WIDGET_ERROR: Final[str] = (
    "Built widget HTML does not exist: {html_path}. Run `belgie run vite build` before starting with dev=False."
)
DEV_WIDGET_ERROR: Final[str] = (
    "Unable to load development widget {url}. "
    "Start the Vite server with `belgie run vite` before starting the MCP server."
)
MISSING_HEAD_ERROR: Final[str] = "Vite widget HTML is missing a <head> element: {url}"


def resolve_widget_path(widget: Path, project_path: Path) -> Path:
    candidate = widget if widget.is_absolute() else project_path / widget
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        msg = MISSING_WIDGET_ERROR.format(widget=candidate)
        raise FileNotFoundError(msg) from error
    if not resolved.is_file() or resolved.name != WIDGET_FILENAME:
        msg = INVALID_WIDGET_FILE_ERROR.format(widget=resolved)
        raise ValueError(msg)
    try:
        resolved.relative_to(project_path)
    except ValueError as error:
        msg = WIDGET_OUTSIDE_PROJECT_ERROR.format(widget=resolved)
        raise ValueError(msg) from error
    return resolved


def widget_name(widget: Path) -> str:
    return widget.parent.name


def built_widget_path(project_path: Path, widget: Path) -> Path:
    return project_path.joinpath(*WIDGET_HTML_RELATIVE_PATH, widget_name(widget), "index.html")


def read_built_widget(project_path: Path, widget: Path) -> str:
    html_path = built_widget_path(project_path, widget).resolve()
    return read_widget_html(html_path)


@cache
def read_widget_html(html_path: Path) -> str:
    if not html_path.is_file():
        msg = MISSING_BUILT_WIDGET_ERROR.format(html_path=html_path)
        raise FileNotFoundError(msg)
    return html_path.read_text(encoding="utf-8")


def development_widget_url(dev_url: str, widget: Path) -> str:
    base_url = normalize_dev_url(dev_url)
    path = f"widgets/{quote(widget_name(widget), safe='')}/index.html"
    return urljoin(f"{base_url}/", path)


def load_development_widget(dev_url: str, widget: Path) -> str:
    url = development_widget_url(dev_url, widget)
    try:
        with urlopen(url, timeout=DEV_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310  # URL scheme validated above.
            html = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as error:
        msg = DEV_WIDGET_ERROR.format(url=url)
        raise RuntimeError(msg) from error
    return inject_base_url(html, dev_url=dev_url, source_url=url)


def normalize_dev_url(dev_url: str) -> str:
    parsed = urlparse(dev_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = INVALID_DEV_URL_ERROR.format(dev_url=dev_url)
        raise ValueError(msg)
    return dev_url.rstrip("/")


def inject_base_url(html: str, *, dev_url: str, source_url: str) -> str:
    head = "<head>"
    if head not in html:
        msg = MISSING_HEAD_ERROR.format(url=source_url)
        raise ValueError(msg)
    base_url = normalize_dev_url(dev_url)
    base = f'<base href="{escape(f"{base_url}/", quote=True)}" />'
    return html.replace(head, f"{head}\n{base}", 1)
