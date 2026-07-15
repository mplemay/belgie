from pathlib import Path

import pytest

from belgie.mcp._manifest import absolutize_asset_urls, load_widget_manifest, normalize_base_url, resolve_project_path


def test_normalize_base_url_accepts_http_urls() -> None:
    assert normalize_base_url("http://127.0.0.1:3001/") == "http://127.0.0.1:3001"


def test_normalize_base_url_rejects_relative_urls() -> None:
    with pytest.raises(ValueError, match="absolute http"):
        normalize_base_url("/assets")


def test_resolve_project_path_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_project_path(None) == tmp_path.resolve()


def test_load_widget_manifest_reads_built_html_and_absolutizes_assets(tmp_path: Path) -> None:
    html_path = tmp_path / "dist" / "widgets" / "clock" / "index.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(
        '<script src="/assets/clock.js"></script><link href="./assets/clock.css">',
        encoding="utf-8",
    )

    manifest = load_widget_manifest(base_url="https://widgets.example.com/", project_path=tmp_path)

    assert manifest.base_url == "https://widgets.example.com"
    assert manifest.widgets["clock"].html == (
        '<script src="https://widgets.example.com/assets/clock.js"></script>'
        '<link href="https://widgets.example.com/assets/clock.css">'
    )


def test_load_widget_manifest_rejects_missing_output(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="belgie run vite build"):
        load_widget_manifest(base_url="https://widgets.example.com", project_path=tmp_path)


def test_absolutize_asset_urls_leaves_inline_html_unchanged() -> None:
    html = '<script type="module">console.log("inline")</script>'

    assert absolutize_asset_urls(html, "https://widgets.example.com") == html
