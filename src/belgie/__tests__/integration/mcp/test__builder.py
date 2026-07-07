from __future__ import annotations

import sys
from pathlib import Path

import pytest

from belgie.mcp._builder import MCP_PACKAGE_DIR, _load_build_dependencies, build_widget

pytestmark = pytest.mark.integration

SKIP_WIN32_VITE_NATIVE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Vite build loads Rollup's native Node-API addon",
)


@SKIP_WIN32_VITE_NATIVE
def test_build_widget_html_returns_inline_html_document(tmp_path: Path) -> None:
    root = tmp_path / "widgets"
    widget_dir = root / "hello"
    widget_dir.mkdir(parents=True)
    (widget_dir / "global.css").write_text(".message { color: rebeccapurple; }\n", encoding="utf-8")
    (widget_dir / "widget.tsx").write_text(
        """
import { render } from "@belgie/widget";
import { useState } from "react";
import "./global.css";

function App() {
  const [message] = useState("Hello from Belgie");
  return <p className="message">{message}</p>;
}

export default function widget() {
  return render({ metadata: { title: "Hello" }, widget: <App /> });
}
""".lstrip(),
        encoding="utf-8",
    )

    result = build_widget(root=root, path=Path("hello/widget.tsx"))
    html = result.html

    assert "<!doctype html>" in html
    assert '<script type="module"' in html
    assert "<style" in html
    assert "Hello from Belgie" in html
    assert 'src="/assets/' not in html
    assert 'href="/assets/' not in html
    assert not (root / "dist").exists()
    assert not (root / "node_modules").exists()
    assert result.manifest.package_name == "@belgie/widget"
    assert result.manifest.package_version == "0.0.0"
    dependencies = _load_build_dependencies()
    widget_dependency = dependencies["@belgie/widget"]
    assert widget_dependency.startswith("file:")
    assert widget_dependency.endswith("_widget_package")
    assert (MCP_PACKAGE_DIR / "_widget_package").resolve().as_posix() in widget_dependency
