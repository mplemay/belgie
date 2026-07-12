import { describe, expect, it } from "vitest";

import { buildVirtualEntry, renderWidgetHtmlDocument } from "./html.js";

describe("buildVirtualEntry", () => {
  it("imports mountWidget and the widget default export", () => {
    const source = buildVirtualEntry("/abs/path/to/hello.tsx");
    expect(source).toContain('import { mountWidget } from "@belgie/mcp";');
    expect(source).toContain('import Widget from "/abs/path/to/hello.tsx";');
    expect(source).toContain("mountWidget(Widget);");
  });

  it("JSON-escapes the widget path", () => {
    const source = buildVirtualEntry('/path/with "quotes".tsx');
    expect(source).toContain('import Widget from "/path/with \\"quotes\\".tsx";');
  });

  it("normalizes Windows path separators to forward slashes", () => {
    const source = buildVirtualEntry("C:\\widgets\\hello.tsx");
    expect(source).toContain('import Widget from "C:/widgets/hello.tsx";');
    expect(source).not.toContain("\\");
  });
});

describe("renderWidgetHtmlDocument", () => {
  it("renders doctype, root, styles, and scripts", () => {
    const html = renderWidgetHtmlDocument({
      scripts: ["/assets/hello.js"],
      styles: ["/assets/hello.css"],
    });
    expect(html).toContain("<!doctype html>");
    expect(html).toContain('<div id="root"></div>');
    expect(html).toContain('<link rel="stylesheet" crossorigin href="/assets/hello.css">');
    expect(html).toContain('<script type="module" crossorigin src="/assets/hello.js"></script>');
  });

  it("renders a valid shell with empty styles and scripts", () => {
    const html = renderWidgetHtmlDocument({ scripts: [], styles: [] });
    expect(html).toContain("<!doctype html>");
    expect(html).toContain("<head>");
    expect(html).toContain('<meta charset="utf-8" />');
    expect(html).toContain('<div id="root"></div>');
    expect(html).not.toContain("<link ");
    expect(html).not.toContain("<script ");
  });
});
