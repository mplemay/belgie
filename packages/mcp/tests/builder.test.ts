import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, test } from "vitest";

import { buildWidget, validateVirtualPath } from "../src/builder.ts";

const temporaryDirectories: string[] = [];

function temporaryProject(): string {
  const root = mkdtempSync(join(tmpdir(), "belgie-widget-builder-"));
  temporaryDirectories.push(root);
  mkdirSync(join(root, "node_modules", "@belgie"), { recursive: true });
  symlinkSync(process.cwd(), join(root, "node_modules", "@belgie", "mcp"), "dir");
  for (const dependency of ["react", "react-dom", "zod"]) {
    symlinkSync(join(process.cwd(), "node_modules", dependency), join(root, "node_modules", dependency), "dir");
  }
  return root;
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("virtual project validation", () => {
  test.each([
    "",
    ".",
    "../outside.ts",
    "nested/../outside.ts",
    "/absolute.ts",
    "C:\\absolute.ts",
    "nested\\windows.ts",
    "widget.tsx",
    "nul\0file.ts",
  ])("rejects invalid virtual path %j", (fileName) => {
    assert.throws(() => validateVirtualPath(fileName), /virtual file path|widget field/u);
  });

  test("accepts normalized POSIX-relative paths", () => {
    assert.doesNotThrow(() => validateVirtualPath("components/Card.tsx"));
  });
});

describe("in-memory widget builds", () => {
  test("builds relative modules, JSON, CSS, and textual assets into stable HTML", async () => {
    const root = temporaryProject();
    const options = {
      root,
      widget: [
        'import "./styles.css";',
        'import { Card } from "./components/Card";',
        'import data from "./data.json";',
        'import note from "./note.txt?raw";',
        'import icon from "./icon.svg";',
        "export default function Widget() {",
        "  return <Card>{data.label}:{note}:{icon}</Card>;",
        "}",
      ].join("\n"),
      files: {
        "components/Card.tsx": "export function Card({ children }) { return <div className=\"card\">{children}</div>; }",
        "data.json": '{"label":"weather"}',
        "icon.svg": '<svg xmlns="http://www.w3.org/2000/svg"><circle r="2" /></svg>',
        "note.txt": "sunny",
        "styles.css": ".card { color: rgb(1, 2, 3); }",
      },
    };

    const first = await buildWidget(options);
    const second = await buildWidget(options);
    assert.equal(first.html, second.html);
    assert.match(first.html, /^<!doctype html>/u);
    assert.match(first.html, /<style>.*(?:rgb\(1,2,3\)|#010203)/su);
    assert.match(first.html, /sunny/u);
    assert.match(first.html, /data:image\/svg\+xml/u);
    const documentHead = first.html.slice(0, first.html.indexOf("<script type=\"module\">"));
    assert.doesNotMatch(documentHead, /<script[^>]+src=/u);
    assert.doesNotMatch(documentHead, /<link[^>]+href=/u);
  });

  test("does not evaluate widget source or discover user Vite configuration", async () => {
    const root = temporaryProject();
    writeFileSync(join(root, "vite.config.ts"), 'throw new Error("loaded user config");\n');
    delete (globalThis as Record<string, unknown>).belgieWidgetEvaluated;

    const result = await buildWidget({
      root,
      widget: [
        "globalThis.belgieWidgetEvaluated = true;",
        'throw new Error("widget source executed");',
        "export default function Widget() { return null; }",
      ].join("\n"),
    });

    assert.match(result.html, /widget source executed/u);
    assert.equal((globalThis as Record<string, unknown>).belgieWidgetEvaluated, undefined);
    assert.equal(existsSync(join(root, "dist")), false);
    assert.equal(existsSync(join(root, ".belgie-virtual-widget")), false);
  });

  test("enforces default exports and reports virtual filenames", async () => {
    const root = temporaryProject();
    await assert.rejects(
      buildWidget({ root, widget: "export const Widget = () => null;" }),
      /widget\.tsx is missing a default export/u,
    );
    await assert.rejects(
      buildWidget({
        root,
        widget: 'import "\.\/missing"; export default function Widget() { return null; }',
      }),
      (error: unknown) => {
        assert(error instanceof Error);
        assert.match(error.message, /virtual import not found/u);
        assert.match(error.message, /widget\.tsx/u);
        assert.equal(error.message.includes(root), false);
        return true;
      },
    );
  });

  test.each(["vite", "node:fs", "file:///tmp/file.ts", "https://example.com/code.ts", "npm:react", "deno:fs", "/tmp/file.ts"])(
    "blocks untrusted import %s",
    async (specifier) => {
      const root = temporaryProject();
      await assert.rejects(
        buildWidget({
          root,
          widget: `import ${JSON.stringify(specifier)};\nexport default function Widget() { return null; }`,
        }),
        /internal package import is not allowed|not allowlisted|scheme or absolute path is not allowed/u,
      );
    },
  );

  test.each(["vite", "vite/plugin", "rolldown", "lightningcss", "@belgie/mcp/vite", "@belgie/mcp/builder"])(
    "keeps internal package %s unavailable when explicitly allowlisted",
    async (specifier) => {
      const root = temporaryProject();
      await assert.rejects(
        buildWidget({
          root,
          widget: `import ${JSON.stringify(specifier)};\nexport default function Widget() { return null; }`,
          dependencies: [specifier],
        }),
        /internal package import is not allowed/u,
      );
    },
  );

  test("allows only explicitly supplied host package aliases", async () => {
    const root = temporaryProject();
    const widget = [
      'import { z } from "zod";',
      "const value = z.string().parse(\"ok\");",
      "export default function Widget() { return <div>{value}</div>; }",
    ].join("\n");
    await assert.rejects(buildWidget({ root, widget }), /not allowlisted/u);
    const result = await buildWidget({ root, widget, dependencies: ["zod"] });
    assert.match(result.html, /<script type="module">/u);
  });

  test("rejects malformed dependency aliases and non-text files", async () => {
    const root = temporaryProject();
    await assert.rejects(
      buildWidget({ root, widget: "export default function Widget() { return null; }", dependencies: ["node:fs"] }),
      /invalid dependency alias/u,
    );
    await assert.rejects(
      buildWidget({
        root,
        widget: "export default function Widget() { return null; }",
        files: { "data.json": 42 as never },
      }),
      /must contain text/u,
    );
  });
});
