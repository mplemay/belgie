import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { afterEach, describe, expect, it } from "vitest";
import { build } from "vite";

import { belgie } from "./vite.js";

const PACKAGE_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const tempDirs: string[] = [];

function makeProject(): string {
  const dir = mkdtempSync(join(tmpdir(), "belgie-vite-"));
  tempDirs.push(dir);
  return dir;
}

function writeWidget(project: string, relativePath: string, code: string): void {
  const filePath = join(project, "src", "widgets", relativePath);
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, code, "utf-8");
}

async function buildProject(project: string): Promise<void> {
  const nodeModules = join(PACKAGE_ROOT, "node_modules");
  await build({
    configFile: false,
    root: project,
    mode: "production",
    logLevel: "silent",
    plugins: [belgie(), react()],
    resolve: {
      alias: {
        "@belgie/mcp": join(PACKAGE_ROOT, "src", "index.tsx"),
        "@modelcontextprotocol/ext-apps": join(
          nodeModules,
          "@modelcontextprotocol",
          "ext-apps",
        ),
        react: join(nodeModules, "react"),
        "react-dom": join(nodeModules, "react-dom"),
        "react/jsx-runtime": join(nodeModules, "react", "jsx-runtime.js"),
        "react/jsx-dev-runtime": join(nodeModules, "react", "jsx-dev-runtime.js"),
      },
    },
    build: {
      // Vite 8 keeps build.outDir relative; belgie writeBundle uses it as-is,
      // so pass an absolute path when root !== process.cwd().
      outDir: join(project, "dist"),
      emptyOutDir: true,
    },
  });
}

afterEach(() => {
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    if (dir) {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

describe("belgie vite plugin", () => {
  it("builds widgets and writes dist/widgets/<name>/index.html", async () => {
    const project = makeProject();
    writeWidget(
      project,
      "hello/index.tsx",
      [
        'import { Widget } from "@belgie/mcp";',
        "",
        "export default function HelloWidget() {",
        "  return (",
        '    <Widget metadata={{ name: "Hello", version: "1.0.0" }}>',
        "      <p>Hello</p>",
        "    </Widget>",
        "  );",
        "}",
        "",
      ].join("\n"),
    );
    writeWidget(
      project,
      "world.tsx",
      [
        'import { Widget } from "@belgie/mcp";',
        "",
        "export default function WorldWidget() {",
        "  return (",
        '    <Widget metadata={{ name: "World", version: "1.0.0" }}>',
        "      <p>World</p>",
        "    </Widget>",
        "  );",
        "}",
        "",
      ].join("\n"),
    );

    await buildProject(project);

    const helloHtml = readFileSync(
      join(project, "dist", "widgets", "hello", "index.html"),
      "utf-8",
    );
    const worldHtml = readFileSync(
      join(project, "dist", "widgets", "world", "index.html"),
      "utf-8",
    );
    expect(helloHtml).toContain("<!doctype html>");
    expect(helloHtml).toContain('<div id="root"></div>');
    expect(helloHtml).toMatch(/src="\/assets\/[^"]+\.js"/);
    expect(worldHtml).toMatch(/src="\/assets\/[^"]+\.js"/);
  }, 60_000);

  it("fails the build when a widget is missing a default export", async () => {
    const project = makeProject();
    writeWidget(
      project,
      "broken/index.tsx",
      "export function Broken() {\n  return <p>broken</p>;\n}\n",
    );

    await expect(buildProject(project)).rejects.toThrow(/missing a default export/);
  }, 60_000);

  it("fails the build when widget names collide", async () => {
    const project = makeProject();
    writeWidget(project, "hello.tsx", "export default function Hello() {\n  return <p>a</p>;\n}\n");
    writeWidget(
      project,
      "hello/index.tsx",
      "export default function HelloDir() {\n  return <p>b</p>;\n}\n",
    );

    await expect(buildProject(project)).rejects.toThrow(/duplicate widget name "hello"/);
  }, 60_000);
});
