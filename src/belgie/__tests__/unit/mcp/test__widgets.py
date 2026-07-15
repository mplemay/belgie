from email.message import EmailMessage
from pathlib import Path
from typing import Never
from urllib.error import HTTPError, URLError

import pytest

from belgie.mcp import _widgets as widgets_module
from belgie.mcp._widgets import (
    built_widget_path,
    development_widget_url,
    inject_base_url,
    load_development_widget,
    normalize_dev_url,
    read_built_widget,
    resolve_widget_path,
    widget_name,
)


def write_widget(project: Path, name: str = "clock") -> Path:
    widget = project / "src" / "widgets" / name / "widget.tsx"
    widget.parent.mkdir(parents=True)
    widget.write_text("export default function Widget() {}\n", encoding="utf-8")
    return widget


def test_resolve_widget_path_accepts_absolute_and_project_relative_paths(tmp_path: Path) -> None:
    widget = write_widget(tmp_path)

    assert resolve_widget_path(widget, tmp_path) == widget.resolve()
    assert resolve_widget_path(widget.relative_to(tmp_path), tmp_path) == widget.resolve()
    assert widget_name(widget) == "clock"


def test_resolve_widget_path_rejects_missing_wrong_named_and_outside_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        resolve_widget_path(Path("src/widgets/missing/widget.tsx"), tmp_path)

    wrong_name = tmp_path / "src" / "widgets" / "clock" / "index.tsx"
    wrong_name.parent.mkdir(parents=True)
    wrong_name.write_text("export default function Widget() {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="widget.tsx"):
        resolve_widget_path(wrong_name, tmp_path)

    outside = tmp_path.parent / f"{tmp_path.name}-outside" / "widget.tsx"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("export default function Widget() {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stay inside"):
        resolve_widget_path(outside, tmp_path)


def test_built_widget_path_and_read_built_widget_use_convention(tmp_path: Path) -> None:
    widget = write_widget(tmp_path)
    html_path = tmp_path / "dist" / "widgets" / "clock" / "index.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html>clock</html>", encoding="utf-8")

    assert built_widget_path(tmp_path, widget) == html_path
    assert read_built_widget(tmp_path, widget) == "<html>clock</html>"


def test_read_built_widget_reports_build_command(tmp_path: Path) -> None:
    widget = write_widget(tmp_path)

    with pytest.raises(FileNotFoundError, match="belgie run vite build"):
        read_built_widget(tmp_path, widget)


def test_development_widget_url_and_base_tag_use_dev_origin(tmp_path: Path) -> None:
    widget = write_widget(tmp_path, "get time")

    assert development_widget_url("http://127.0.0.1:5173/", widget) == (
        "http://127.0.0.1:5173/widgets/get%20time/index.html"
    )
    assert inject_base_url(
        "<!doctype html><html><head></head><body></body></html>",
        dev_url="http://127.0.0.1:5173",
        source_url="http://127.0.0.1:5173/widgets/get%20time/index.html",
    ) == ('<!doctype html><html><head>\n<base href="http://127.0.0.1:5173/" /></head><body></body></html>')


def test_normalize_dev_url_accepts_http_urls_and_rejects_relative_urls() -> None:
    assert normalize_dev_url("http://127.0.0.1:5173/") == "http://127.0.0.1:5173"

    with pytest.raises(ValueError, match="absolute http"):
        normalize_dev_url("/assets")


def test_inject_base_url_rejects_invalid_html() -> None:
    with pytest.raises(ValueError, match="missing a <head>"):
        inject_base_url("<html></html>", dev_url="http://127.0.0.1:5173", source_url="http://example.com")


def test_load_development_widget_reports_unavailable_vite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = write_widget(tmp_path)

    def unavailable(*_args: object, **_kwargs: object) -> Never:
        reason = "connection refused"
        raise URLError(reason)

    monkeypatch.setattr(widgets_module, "urlopen", unavailable)

    with pytest.raises(RuntimeError, match="Start the Vite server"):
        load_development_widget("http://127.0.0.1:5173", widget)


def test_load_development_widget_reports_http_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = write_widget(tmp_path)
    widget_url = "http://127.0.0.1:5173/widgets/clock/index.html"
    not_found_msg = "Not Found"

    def not_found(*_args: object, **_kwargs: object) -> Never:
        raise HTTPError(widget_url, 404, not_found_msg, EmailMessage(), None)

    monkeypatch.setattr(widgets_module, "urlopen", not_found)

    with pytest.raises(RuntimeError, match="Vite returned HTTP 404") as error:
        load_development_widget("http://127.0.0.1:5173", widget)
    assert "Start the Vite server" not in str(error.value)
