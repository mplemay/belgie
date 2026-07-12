import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  assertNoInvalidWidgets,
  assertUniqueWidgetNames,
  discoverWidgetsSync,
  scanWidgetsSync,
  type WidgetCandidate,
} from "./scan-widgets.js";

const tempDirs: string[] = [];

function makeSrcDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "belgie-scan-"));
  tempDirs.push(dir);
  return dir;
}

function writeWidget(srcDir: string, relativePath: string, code: string): string {
  const filePath = join(srcDir, relativePath);
  mkdirSync(join(filePath, ".."), { recursive: true });
  writeFileSync(filePath, code, "utf-8");
  return filePath;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    if (dir) {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

describe("scanWidgetsSync", () => {
  it("discovers flat and directory widgets with default exports", () => {
    const srcDir = makeSrcDir();
    const hello = writeWidget(srcDir, "hello.tsx", "export default function Hello() {}");
    const world = writeWidget(srcDir, "world/index.tsx", "export default function World() {}");

    const { valid, invalid } = scanWidgetsSync(srcDir);
    expect(invalid).toEqual([]);
    expect(valid).toEqual(
      expect.arrayContaining([
        { name: "hello", filePath: hello },
        { name: "world", filePath: world },
      ]),
    );
    expect(valid).toHaveLength(2);
  });

  it('filters out widgets named "index"', () => {
    const srcDir = makeSrcDir();
    writeWidget(srcDir, "index.tsx", "export default function Index() {}");
    writeWidget(srcDir, "hello.tsx", "export default function Hello() {}");

    const { valid } = scanWidgetsSync(srcDir);
    expect(valid.map((widget) => widget.name)).toEqual(["hello"]);
  });

  it("marks widgets without a default export as invalid", () => {
    const srcDir = makeSrcDir();
    const broken = writeWidget(srcDir, "broken.tsx", "export function Broken() {}");
    writeWidget(srcDir, "ok.tsx", "export default function Ok() {}");

    const { valid, invalid } = scanWidgetsSync(srcDir);
    expect(valid.map((widget) => widget.name)).toEqual(["ok"]);
    expect(invalid).toEqual([{ filePath: broken }]);
  });
});

describe("assertUniqueWidgetNames", () => {
  it("passes for unique names", () => {
    expect(() =>
      assertUniqueWidgetNames([
        { name: "hello", filePath: "/a/hello.tsx" },
        { name: "world", filePath: "/a/world/index.tsx" },
      ]),
    ).not.toThrow();
  });

  it("throws listing both paths for duplicate names", () => {
    const widgets: WidgetCandidate[] = [
      { name: "hello", filePath: "/a/hello.tsx" },
      { name: "hello", filePath: "/a/hello/index.tsx" },
    ];
    expect(() => assertUniqueWidgetNames(widgets)).toThrow(
      /duplicate widget name "hello"[\s\S]*\/a\/hello\.tsx[\s\S]*\/a\/hello\/index\.tsx/,
    );
  });
});

describe("assertNoInvalidWidgets", () => {
  it("passes for an empty list", () => {
    expect(() => assertNoInvalidWidgets([])).not.toThrow();
  });

  it("throws listing invalid paths", () => {
    expect(() => assertNoInvalidWidgets([{ filePath: "/a/broken.tsx" }])).toThrow(
      /missing a default export[\s\S]*\/a\/broken\.tsx/,
    );
  });
});

describe("discoverWidgetsSync", () => {
  it("returns valid unique widgets", () => {
    const srcDir = makeSrcDir();
    writeWidget(srcDir, "hello.tsx", "export default function Hello() {}");
    writeWidget(srcDir, "world/index.jsx", "export default function World() {}");

    const widgets = discoverWidgetsSync(srcDir);
    expect(widgets.map((widget) => widget.name).sort()).toEqual(["hello", "world"]);
  });

  it("throws on duplicate names", () => {
    const srcDir = makeSrcDir();
    writeWidget(srcDir, "hello.tsx", "export default function Hello() {}");
    writeWidget(srcDir, "hello/index.tsx", "export default function HelloDir() {}");

    expect(() => discoverWidgetsSync(srcDir)).toThrow(/duplicate widget name "hello"/);
  });
});
