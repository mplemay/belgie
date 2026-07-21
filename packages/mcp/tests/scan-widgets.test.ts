import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

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
    temporaryDirectories.splice(0).map(async (directory) => rm(directory, { force: true, recursive: true })),
  );
});

describe("widget scanning", () => {
  it("classifies direct widget entries and ignores nested files", async () => {
    const srcDir = await temporaryWidgets();
    await mkdir(join(srcDir, "clock"), { recursive: true });
    await mkdir(join(srcDir, "invalid"), { recursive: true });
    await mkdir(join(srcDir, "nested", "child"), { recursive: true });
    await writeFile(join(srcDir, "clock", "widget.tsx"), "export default function Clock() { return null; }\n");
    await writeFile(join(srcDir, "invalid", "widget.tsx"), "export function Invalid() { return null; }\n");
    await writeFile(
      join(srcDir, "nested", "child", "widget.tsx"),
      "export default function Nested() { return null; }\n",
    );

    const result = scanWidgetsSync(srcDir);

    expect(result.valid).toStrictEqual([
      {
        filePath: resolve(srcDir, "clock", "widget.tsx"),
        name: "clock",
      },
    ]);
    expect(result.invalid).toStrictEqual([{ filePath: resolve(srcDir, "invalid", "widget.tsx") }]);
    expect(discoverWidgetsSync(srcDir)).toStrictEqual(result.valid);
  });

  it("returns empty results when the source directory is absent", () => {
    const srcDir = join(tmpdir(), "belgie-mcp-does-not-exist");
    expect(scanWidgetsSync(srcDir)).toStrictEqual({ invalid: [], valid: [] });
  });

  it("reports duplicate names with every source path", () => {
    expect(() => {
      assertUniqueWidgetNames([
        { filePath: "/first/widget.tsx", name: "clock" },
        { filePath: "/second/widget.tsx", name: "clock" },
      ]);
    }).toThrow(/duplicate widget name "clock".*first.*second/su);
    expect(() => {
      assertUniqueWidgetNames([{ filePath: "/widget.tsx", name: "clock" }]);
    }).not.toThrow();
  });

  it("reports every widget missing a default export", () => {
    expect(() => {
      assertNoInvalidWidgets([]);
    }).not.toThrow();
    expect(() => {
      assertNoInvalidWidgets([{ filePath: "/first/widget.tsx" }, { filePath: "/second/widget.tsx" }]);
    }).toThrow(/missing a default export.*first.*second/su);
  });
});
