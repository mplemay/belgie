import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { afterEach, describe, expect, test } from "vitest";

import {
  assertNoInvalidWidgets,
  assertUniqueWidgetNames,
  discoverWidgetsSync,
  scanWidgetsSync,
} from "../src/scan-widgets.ts";

const temporaryDirectories: string[] = [];

async function temporaryWidgets(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "belgie-mcp-scan-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(async () => {
  const { rm } = await import("node:fs/promises");
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { force: true, recursive: true }),
    ),
  );
});

describe("widget scanning", () => {
  test("classifies direct widget entries and ignores nested files", async () => {
    const srcDir = await temporaryWidgets();
    await mkdir(join(srcDir, "clock"), { recursive: true });
    await mkdir(join(srcDir, "invalid"), { recursive: true });
    await mkdir(join(srcDir, "nested", "child"), { recursive: true });
    await writeFile(
      join(srcDir, "clock", "widget.tsx"),
      "export default function Clock() { return null; }\n",
    );
    await writeFile(
      join(srcDir, "invalid", "widget.tsx"),
      "export function Invalid() { return null; }\n",
    );
    await writeFile(
      join(srcDir, "nested", "child", "widget.tsx"),
      "export default function Nested() { return null; }\n",
    );

    const result = scanWidgetsSync(srcDir);

    expect(result.valid).toEqual([
      {
        filePath: resolve(srcDir, "clock", "widget.tsx"),
        name: "clock",
      },
    ]);
    expect(result.invalid).toEqual([
      { filePath: resolve(srcDir, "invalid", "widget.tsx") },
    ]);
    expect(discoverWidgetsSync(srcDir)).toEqual(result.valid);
  });

  test("returns empty results when the source directory is absent", () => {
    const srcDir = join(tmpdir(), "belgie-mcp-does-not-exist");
    expect(scanWidgetsSync(srcDir)).toEqual({ invalid: [], valid: [] });
  });

  test("reports duplicate names with every source path", () => {
    expect(() =>
      assertUniqueWidgetNames([
        { name: "clock", filePath: "/first/widget.tsx" },
        { name: "clock", filePath: "/second/widget.tsx" },
      ]),
    ).toThrow(/duplicate widget name "clock".*first.*second/su);
    expect(() =>
      assertUniqueWidgetNames([{ name: "clock", filePath: "/widget.tsx" }]),
    ).not.toThrow();
  });

  test("reports every widget missing a default export", () => {
    expect(() => assertNoInvalidWidgets([])).not.toThrow();
    expect(() =>
      assertNoInvalidWidgets([
        { filePath: "/first/widget.tsx" },
        { filePath: "/second/widget.tsx" },
      ]),
    ).toThrow(/missing a default export.*first.*second/su);
  });
});
