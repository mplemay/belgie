import { createElement } from "react";
import { afterEach, describe, expect, test } from "vitest";

import { render } from "../src/index.ts";

const CONTEXT_SYMBOL = Symbol.for("@belgie/render/context");

function installContext(source: string): void {
  Object.defineProperty(globalThis, CONTEXT_SYMBOL, {
    configurable: true,
    value: Object.freeze({ source, url: "file:///__deno_python_inline__.tsx", version: 1 }),
  });
}

afterEach(() => {
  Reflect.deleteProperty(globalThis, CONTEXT_SYMBOL);
});

describe("render", () => {
  test("returns a self-contained HTML document and applies server-side plugins", async () => {
    installContext([
      'import { render } from "npm:@belgie/render";',
      'import serverOnly from "jsr:@example/server-plugin";',
      "function Widget() { return <main className=\"card\">plugin-target</main>; }",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverOnly()] });",
      "}",
    ].join("\n"));

    const html = await render({
      widget: createElement("main", null, "plugin-target"),
      plugins: [
        {
          name: "server-secret-plugin",
          transform(code, id) {
            return id.includes("belgie-render/caller") ? code.replace("plugin-target", "plugin-applied") : null;
          },
        },
      ],
    });

    expect(html).toMatch(/^<!doctype html>/u);
    expect(html).toContain("plugin-applied");
    expect(html).not.toContain("server-secret-plugin");
    expect(html).not.toContain("serverOnly");
    expect(html).not.toContain("jsr:@example/server-plugin");
    expect(html).toContain('<div id="root"></div>');
  });

  test("uses the default empty plugin list", async () => {
    installContext('import { render } from "@belgie/render"; export default () => render({ widget: <main>plain</main> });');

    const html = await render({ widget: createElement("main", null, "plain") });

    expect(html).toContain("plain");
  });

  test("restores the process environment after a build", async () => {
    installContext('import { render } from "@belgie/render"; export default () => render({ widget: <main>env</main> });');
    const environment = process.env;

    await render({ widget: createElement("main", null, "env") });

    expect(process.env).toBe(environment);
  });

  test("inlines CSS emitted by a client dependency", async () => {
    installContext([
      'import { render } from "@belgie/render";',
      'import "virtual:inline-style.css";',
      "export const run = () => render({ widget: <main>styled</main> });",
    ].join("\n"));

    const html = await render({
      widget: createElement("main", null, "styled"),
      plugins: [
        {
          name: "inline-style",
          resolveId(id) {
            return id === "virtual:inline-style.css" ? `\0${id}` : null;
          },
          load(id) {
            return id === "\0virtual:inline-style.css" ? ".card { color: rebeccapurple; }" : null;
          },
        },
      ],
    });

    expect(html).toContain(".card{color:#639}");
    expect(html.slice(0, html.indexOf("</head>"))).not.toContain("<link");
  });

  test("rejects invalid inputs and missing runtime context", async () => {
    await expect(render({ widget: "not an element" as never })).rejects.toThrow("widget must be a React element");
    await expect(render({ widget: createElement("main") })).rejects.toThrow("missing Belgie inline script context");

    installContext('import { render } from "@belgie/render"; export default () => render({ widget: <main /> });');
    await expect(render({ plugins: {} as never, widget: createElement("main") })).rejects.toThrow(
      "plugins must be an array",
    );
  });

  test.each([
    ["filesystem output", { name: "write", config: () => ({ build: { write: true } }) }, "filesystem output"],
    [
      "code splitting",
      { name: "chunks", config: () => ({ build: { rolldownOptions: { output: { codeSplitting: true } } } }) },
      "code splitting",
    ],
  ])("rejects plugin attempts to enable %s", async (_name, plugin, message) => {
    installContext('import { render } from "@belgie/render"; export default () => render({ widget: <main /> });');
    await expect(render({ plugins: [plugin], widget: createElement("main") })).rejects.toThrow(message);
  });

  test("rejects non-CSS build assets", async () => {
    installContext('import { render } from "@belgie/render"; export default () => render({ widget: <main /> });');
    await expect(
      render({
        plugins: [
          {
            name: "asset",
            buildStart() {
              this.emitFile({ fileName: "secret.txt", source: "secret", type: "asset" });
            },
          },
        ],
        widget: createElement("main"),
      }),
    ).rejects.toThrow("emitted non-CSS assets");
  });
});
