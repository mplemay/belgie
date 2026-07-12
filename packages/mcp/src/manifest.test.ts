import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { loadWidgetManifest } from "./manifest.js";

const tempDirs: string[] = [];

function makeProject(): string {
  const dir = mkdtempSync(join(tmpdir(), "belgie-manifest-"));
  tempDirs.push(dir);
  return dir;
}

function writeWidgetHtml(projectRoot: string, name: string, html: string): void {
  const widgetDir = join(projectRoot, "dist", "widgets", name);
  mkdirSync(widgetDir, { recursive: true });
  writeFileSync(join(widgetDir, "index.html"), html, "utf-8");
}

afterEach(() => {
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    if (dir) {
      rmSync(dir, { recursive: true, force: true });
    }
  }
});

describe("loadWidgetManifest", () => {
  it("loads multiple widgets and normalizes trailing slash on baseUrl", () => {
    const project = makeProject();
    writeWidgetHtml(
      project,
      "hello",
      '<!doctype html><script type="module" src="/assets/hello.js"></script>',
    );
    writeWidgetHtml(
      project,
      "world",
      '<!doctype html><link rel="stylesheet" href="/assets/world.css">',
    );

    const manifest = loadWidgetManifest(project, "http://127.0.0.1:3001/");
    expect(manifest.baseUrl).toBe("http://127.0.0.1:3001");
    expect(Object.keys(manifest.widgets).sort()).toEqual(["hello", "world"]);
    expect(manifest.widgets.hello.name).toBe("hello");
    expect(manifest.widgets.hello.html).toContain(
      'src="http://127.0.0.1:3001/assets/hello.js"',
    );
    expect(manifest.widgets.world.html).toContain(
      'href="http://127.0.0.1:3001/assets/world.css"',
    );
  });

  it("absolutizes /assets, assets, and ./assets for src and href", () => {
    const project = makeProject();
    writeWidgetHtml(
      project,
      "urls",
      [
        "<!doctype html>",
        '<script src="/assets/a.js"></script>',
        '<script src="assets/b.js"></script>',
        '<script src="./assets/c.js"></script>',
        '<link href="/assets/a.css">',
        '<link href="assets/b.css">',
        '<link href="./assets/c.css">',
      ].join(""),
    );

    const html = loadWidgetManifest(project, "https://cdn.example").widgets.urls.html;
    expect(html).toContain('src="https://cdn.example/assets/a.js"');
    expect(html).toContain('src="https://cdn.example/assets/b.js"');
    expect(html).toContain('src="https://cdn.example/assets/c.js"');
    expect(html).toContain('href="https://cdn.example/assets/a.css"');
    expect(html).toContain('href="https://cdn.example/assets/b.css"');
    expect(html).toContain('href="https://cdn.example/assets/c.css"');
    expect(html).not.toContain('src="/assets/');
    expect(html).not.toContain('href="./assets/');
  });

  it("throws when dist/widgets is missing", () => {
    const project = makeProject();
    expect(() => loadWidgetManifest(project, "http://localhost")).toThrow(
      /No widget HTML found under .*dist\/widgets/,
    );
  });

  it("throws when dist/widgets is empty", () => {
    const project = makeProject();
    mkdirSync(join(project, "dist", "widgets"), { recursive: true });
    expect(() => loadWidgetManifest(project, "http://localhost")).toThrow(
      /No widget HTML found under .*dist\/widgets/,
    );
  });

  it("skips non-directories and directories without index.html", () => {
    const project = makeProject();
    writeWidgetHtml(project, "good", "<!doctype html><div id=\"root\"></div>");
    writeFileSync(join(project, "dist", "widgets", "not-a-dir.txt"), "x", "utf-8");
    mkdirSync(join(project, "dist", "widgets", "empty"), { recursive: true });

    const manifest = loadWidgetManifest(project, "http://localhost");
    expect(Object.keys(manifest.widgets)).toEqual(["good"]);
  });
});
