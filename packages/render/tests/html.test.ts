import { escapeInlineScript, escapeInlineStyle, renderBundle, renderHtmlDocument } from "../src/html.ts";
import type { BuildArtifact } from "../src/html.ts";

describe("HTML output", () => {
  it("escapes inline closing tags and renders one complete document", () => {
    const html = renderHtmlDocument('console.log("</ScRiPt>")', ["main::after { content: '</STYLE>' }"]);

    expect(escapeInlineScript("</script>")).toBe(String.raw`<\/script>`);
    expect(escapeInlineStyle("</style>")).toBe(String.raw`<\/style>`);
    expect(html).toMatch(/^<!doctype html>/u);
    expect(html).toContain('<div id="root"></div>');
    expect(html).toContain(String.raw`<\/script>`);
    expect(html).toContain(String.raw`<\/style>`);
    expect(html.endsWith("\n")).toBeTruthy();
  });

  it("inlines CSS assets in deterministic order", () => {
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

  it.each([
    ["entry count", {}, "expected one entry chunk"],
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
