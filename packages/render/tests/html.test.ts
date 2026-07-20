import { describe, expect, test } from "vitest";

import {
  escapeInlineScript,
  escapeInlineStyle,
  renderBundle,
  renderHtmlDocument,
  type BuildArtifact,
} from "../src/html.ts";

describe("HTML output", () => {
  test("escapes inline closing tags and renders one complete document", () => {
    const html = renderHtmlDocument('console.log("</ScRiPt>")', ["main::after { content: '</STYLE>' }"]);

    expect(escapeInlineScript("</script>")).toBe("<\\/script>");
    expect(escapeInlineStyle("</style>")).toBe("<\\/style>");
    expect(html).toMatch(/^<!doctype html>/u);
    expect(html).toContain('<div id="root"></div>');
    expect(html).toContain("<\\/script>");
    expect(html).toContain("<\\/style>");
    expect(html.endsWith("\n")).toBe(true);
  });

  test("inlines CSS assets in deterministic order", () => {
    const html = renderBundle({
      "widget.js": {
        code: "console.log('widget')",
        dynamicImports: [],
        fileName: "widget.js",
        imports: [],
        isEntry: true,
        type: "chunk",
      },
      "z.css": { fileName: "z.css", source: new TextEncoder().encode(".z{}"), type: "asset" },
      "a.css": { fileName: "a.css", source: ".a{}", type: "asset" },
    });

    expect(html.indexOf(".a{}")).toBeLessThan(html.indexOf(".z{}"));
  });

  test.each([
    [
      "entry count",
      {},
      "expected one entry chunk",
    ],
    [
      "extra chunks",
      {
        "entry.js": {
          code: "",
          dynamicImports: [],
          fileName: "entry.js",
          imports: [],
          isEntry: true,
          type: "chunk",
        },
        "extra.js": {
          code: "",
          dynamicImports: [],
          fileName: "extra.js",
          imports: [],
          isEntry: false,
          type: "chunk",
        },
      },
      "emitted extra chunks",
    ],
    [
      "retained imports",
      {
        "entry.js": {
          code: "",
          dynamicImports: ["dependency.js"],
          fileName: "entry.js",
          imports: [],
          isEntry: true,
          type: "chunk",
        },
      },
      "retained imports",
    ],
    [
      "non-CSS assets",
      {
        "entry.js": {
          code: "",
          dynamicImports: [],
          fileName: "entry.js",
          imports: [],
          isEntry: true,
          type: "chunk",
        },
        "image.png": { fileName: "image.png", source: "image", type: "asset" },
      },
      "emitted non-CSS assets",
    ],
    [
      "missing CSS",
      {
        "entry.js": {
          code: "",
          dynamicImports: [],
          fileName: "entry.js",
          imports: [],
          isEntry: true,
          type: "chunk",
          viteMetadata: { importedCss: new Set(["missing.css"]) },
        },
      },
      "references missing CSS asset",
    ],
  ])("rejects %s", (_name, bundle, message) => {
    expect(() => renderBundle(bundle as Record<string, BuildArtifact>)).toThrow(message);
  });
});
