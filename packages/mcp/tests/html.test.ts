import { describe, expect, test } from "vitest";

import {
  buildVirtualEntry,
  escapeInlineScript,
  escapeInlineStyle,
  renderWidgetHtmlDocument,
} from "../src/html.ts";

describe("HTML helpers", () => {
  test("escape closing script and style tags case-insensitively", () => {
    expect(escapeInlineScript("before</ScRiPt>after")).toBe(
      "before<\\/script>after",
    );
    expect(escapeInlineStyle("before</STYLE>after")).toBe(
      "before<\\/style>after",
    );
  });

  test("build a portable virtual widget entry", () => {
    expect(buildVirtualEntry("C:\\widgets\\clock\\widget.tsx")).toBe(
      [
        'import { mountWidget } from "@belgie/mcp";',
        'import Widget from "C:/widgets/clock/widget.tsx";',
        "",
        "mountWidget(Widget);",
        "",
      ].join("\n"),
    );
  });

  test("render external and inline assets in a complete document", () => {
    const html = renderWidgetHtmlDocument({
      inlineScript: 'console.log("</script>");',
      inlineStyles: ["body { content: '</style>'; }"],
      scripts: ["/widget.js"],
      styles: ["/widget.css"],
    });

    expect(html).toContain(
      '<link rel="stylesheet" crossorigin href="/widget.css">',
    );
    expect(html).toContain("<style>body { content: '<\\/style>'; }</style>");
    expect(html).toContain(
      '<script type="module" crossorigin src="/widget.js"></script>',
    );
    expect(html).toContain(
      '<script type="module">console.log("<\\/script>");</script>',
    );
    expect(html).toMatch(/^<!doctype html>/u);
    expect(html).toMatch(/<div id="root"><\/div>/u);
    expect(html.endsWith("\n")).toBe(true);
  });

  test("render the minimal document without optional assets", () => {
    const html = renderWidgetHtmlDocument({});

    expect(html).not.toContain("<link");
    expect(html).not.toContain('<script type="module"');
    expect(html).toContain('<div id="root"></div>');
  });
});
