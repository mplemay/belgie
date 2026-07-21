import { buildVirtualEntry, escapeInlineScript, escapeInlineStyle, renderWidgetHtmlDocument } from "../src/html.ts";

describe("hTML helpers", () => {
  it("escape closing script and style tags case-insensitively", () => {
    expect(escapeInlineScript("before</ScRiPt>after")).toBe(String.raw`before<\/script>after`);
    expect(escapeInlineStyle("before</STYLE>after")).toBe(String.raw`before<\/style>after`);
  });

  it("build a portable virtual widget entry", () => {
    expect(buildVirtualEntry(String.raw`C:\widgets\clock\widget.tsx`)).toBe(
      [
        'import { mountWidget } from "@belgie/mcp";',
        'import Widget from "C:/widgets/clock/widget.tsx";',
        "",
        "mountWidget(Widget);",
        "",
      ].join("\n"),
    );
  });

  it("render external and inline assets in a complete document", () => {
    const html = renderWidgetHtmlDocument({
      inlineScript: 'console.log("</script>");',
      inlineStyles: ["body { content: '</style>'; }"],
      scripts: ["/widget.js"],
      styles: ["/widget.css"],
    });

    expect(html).toContain('<link rel="stylesheet" crossorigin href="/widget.css">');
    expect(html).toContain(String.raw`<style>body { content: '<\/style>'; }</style>`);
    expect(html).toContain('<script type="module" crossorigin src="/widget.js"></script>');
    expect(html).toContain(String.raw`<script type="module">console.log("<\/script>");</script>`);
    expect(html).toMatch(/^<!doctype html>/u);
    expect(html).toMatch(/<div id="root"><\/div>/u);
    expect(html.endsWith("\n")).toBeTruthy();
  });

  it("render the minimal document without optional assets", () => {
    const html = renderWidgetHtmlDocument({});

    expect(html).not.toContain("<link");
    expect(html).not.toContain('<script type="module"');
    expect(html).toContain('<div id="root"></div>');
  });
});
