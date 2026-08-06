import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { buildWidgetFile, loadVitePlugins, packageNameFromSpecifier } from "../src/build.ts";
import { sanitizedProcessReport } from "../src/process-report.ts";

const CLI = resolve(import.meta.dirname, "../dist/cli.js");

describe("package name from specifier", () => {
  it.each([
    ["npm:@tailwindcss/vite@latest", "@tailwindcss/vite"],
    ["@tailwindcss/vite", "@tailwindcss/vite"],
    ["npm:vite-plugin-foo@1.0.0", "vite-plugin-foo"],
    ["vite-plugin-foo", "vite-plugin-foo"],
  ])("parses %s", (specifier, expected) => {
    expect(packageNameFromSpecifier(specifier)).toBe(expected);
  });

  it("rejects jsr plugins", () => {
    expect(() => packageNameFromSpecifier("jsr:@scope/pkg")).toThrow("jsr:");
  });

  it("rejects invalid specifiers", () => {
    expect(() => packageNameFromSpecifier("npm:@scope")).toThrow("invalid plugin specifier");
  });
});

describe("build widget file", () => {
  it("builds a default-export widget into one HTML document", async () => {
    const directory = mkdtempSync(join(tmpdir(), "belgie-vite-widget-"));
    const widgetPath = join(directory, "widget.tsx");
    writeFileSync(widgetPath, "export default function Widget() { return <main>Ready</main>; }\n");

    const previous = process.env.NODE_ENV;
    process.env.NODE_ENV = "test";
    try {
      const html = await buildWidgetFile(widgetPath);
      expect(html).toMatch(/^<!doctype html>/u);
      expect(html).toContain('<div id="root"></div>');
      expect(html).toContain("Ready");
      expect(process.env.NODE_ENV).toBe("test");
    } finally {
      if (previous === undefined) {
        delete process.env.NODE_ENV;
      } else {
        process.env.NODE_ENV = previous;
      }
    }
  });

  it("builds from a relative widget path", async () => {
    const directory = mkdtempSync(join(tmpdir(), "belgie-vite-widget-"));
    const widgetPath = join(directory, "widget.tsx");
    writeFileSync(widgetPath, "export default function Widget() { return <main>Relative</main>; }\n");
    const previousCwd = process.cwd();
    process.chdir(directory);
    try {
      const html = await buildWidgetFile("widget.tsx");
      expect(html).toContain("Relative");
    } finally {
      process.chdir(previousCwd);
    }
  });

  it("rejects widgets without a default export", async () => {
    const directory = mkdtempSync(join(tmpdir(), "belgie-vite-widget-"));
    const widgetPath = join(directory, "widget.tsx");
    writeFileSync(widgetPath, "export function Widget() { return null; }\n");

    await expect(buildWidgetFile(widgetPath)).rejects.toThrow("missing a default export");
  });
});

describe("load vite plugins", () => {
  it("loads a plugin factory from the workspace node_modules", async () => {
    const directory = mkdtempSync(join(tmpdir(), "belgie-vite-plugin-"));
    const packageName = "fixture-vite-plugin";
    const packageRoot = join(directory, "node_modules", packageName);
    mkdirSync(packageRoot, { recursive: true });
    writeFileSync(join(directory, "package.json"), JSON.stringify({ name: "workspace", type: "module" }));
    writeFileSync(
      join(packageRoot, "package.json"),
      JSON.stringify({ name: packageName, type: "module", main: "./index.js" }),
    );
    writeFileSync(
      join(packageRoot, "index.js"),
      "export default function plugin() { return { name: 'fixture-plugin' }; }\n",
    );

    const previousCwd = process.cwd();
    process.chdir(directory);
    try {
      const plugins = await loadVitePlugins([packageName]);
      expect(plugins).toHaveLength(1);
      expect((plugins[0] as { name: string }).name).toBe("fixture-plugin");
    } finally {
      process.chdir(previousCwd);
    }
  });

  it("loads a non-factory default export", async () => {
    const directory = mkdtempSync(join(tmpdir(), "belgie-vite-plugin-"));
    const packageName = "fixture-vite-plugin-object";
    const packageRoot = join(directory, "node_modules", packageName);
    mkdirSync(packageRoot, { recursive: true });
    writeFileSync(join(directory, "package.json"), JSON.stringify({ name: "workspace", type: "module" }));
    writeFileSync(
      join(packageRoot, "package.json"),
      JSON.stringify({ name: packageName, type: "module", main: "./index.js" }),
    );
    writeFileSync(join(packageRoot, "index.js"), "export default { name: 'object-plugin' };\n");

    const previousCwd = process.cwd();
    process.chdir(directory);
    try {
      const plugins = await loadVitePlugins([`npm:${packageName}`]);
      expect((plugins[0] as { name: string }).name).toBe("object-plugin");
    } finally {
      process.chdir(previousCwd);
    }
  });

  it("rejects missing plugins", async () => {
    await expect(loadVitePlugins(["definitely-missing-belgie-plugin-xyz"])).rejects.toThrow("failed to load plugin");
  });
});

describe("sanitized process report", () => {
  it("returns a report without sharedObjects", () => {
    const report = sanitizedProcessReport();
    expect(report.sharedObjects).toBeUndefined();
    expect(report.header).toStrictEqual(expect.any(Object));
  });

  it("reports glibc headers on linux gnu Deno builds", () => {
    const previous = (globalThis as typeof globalThis & { Deno?: unknown }).Deno;
    (globalThis as typeof globalThis & { Deno?: { build: { os: string; env?: string } } }).Deno = {
      build: { os: "linux", env: "gnu" },
    };
    try {
      expect(sanitizedProcessReport().header).toStrictEqual({
        glibcVersionRuntime: "2.38",
        glibcVersionCompiler: "2.38",
      });
    } finally {
      if (previous === undefined) {
        Reflect.deleteProperty(globalThis, "Deno");
      } else {
        (globalThis as typeof globalThis & { Deno?: unknown }).Deno = previous;
      }
    }
  });
});

describe("CLI", () => {
  it("writes HTML to --out", () => {
    const directory = mkdtempSync(join(tmpdir(), "belgie-vite-cli-"));
    const widgetPath = join(directory, "widget.tsx");
    const outPath = join(directory, "widget.html");
    writeFileSync(widgetPath, "export default function Widget() { return <main>CLI</main>; }\n");

    execFileSync(process.execPath, [CLI, "--widget", widgetPath, "--out", outPath], {
      encoding: "utf8",
      env: { ...process.env, NODE_ENV: "production" },
    });

    const html = readFileSync(outPath, "utf8");
    expect(html).toMatch(/^<!doctype html>/u);
    expect(html).toContain("CLI");
  });

  it("prints HTML to stdout without --out", () => {
    const directory = mkdtempSync(join(tmpdir(), "belgie-vite-cli-"));
    const widgetPath = join(directory, "widget.tsx");
    writeFileSync(widgetPath, "export default function Widget() { return <main>stdout</main>; }\n");

    const stdout = execFileSync(process.execPath, [CLI, "--widget", widgetPath], {
      encoding: "utf8",
      env: { ...process.env, NODE_ENV: "production" },
    });
    expect(stdout).toContain("stdout");
  });

  it("prints usage for missing --widget", () => {
    expect(() => execFileSync(process.execPath, [CLI], { encoding: "utf8" })).toThrow(/Usage: @belgie\/vite/);
  });

  it("rejects unknown arguments", () => {
    expect(() => execFileSync(process.execPath, [CLI, "--nope"], { encoding: "utf8" })).toThrow(
      /unknown argument --nope/,
    );
  });
});
