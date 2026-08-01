import { createElement } from "react";

import { buildInlineWidget } from "../src/build.ts";
import { buildFromSource } from "../src/host.ts";
import { isRenderRequest, render, RENDER_REQUEST } from "../src/index.ts";
import { preparePluginsModule } from "../src/source.ts";

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

describe("@belgie/render", () => {
  it("returns a render request sentinel for the host side-channel", async () => {
    installContext('import { render } from "@belgie/render"; export default () => render({ widget: <main /> });');

    const result = await render({ widget: createElement("main") });

    expect(isRenderRequest(result)).toBeTruthy();
    expect(result).toStrictEqual(RENDER_REQUEST);
  });

  it("builds self-contained HTML from sealed source and applies server-side plugins", async () => {
    const source = [
      'import { render } from "npm:@belgie/render";',
      'const serverOnlyMarker = "server-only-plugin-marker";',
      "function serverOnly() {",
      "  return {",
      "    name: serverOnlyMarker,",
      "    renderChunk(code) {",
      '      return code.replace("plugin-target", "plugin-applied");',
      "    },",
      "  };",
      "}",
      'function Widget() { return <main className="card">plugin-target</main>; }',
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverOnly()] });",
      "}",
    ].join("\n");

    const html = await buildFromSource(source);

    expect(html).toMatch(/^<!doctype html>/u);
    expect(html).toContain("plugin-applied");
    expect(html).not.toContain("plugin-target");
    expect(html).not.toContain("server-only-plugin-marker");
    expect(html).toContain('<div id="root"></div>');
  });

  it("applies server plugins when the module also binds common names like name and code", async () => {
    const source = [
      'import { render } from "npm:@belgie/render";',
      'const name = "display-name";',
      'const code = "display-code";',
      "function serverOnly() {",
      "  return {",
      '    name: "server-only-plugin",',
      "    renderChunk(code) {",
      '      return code.replace("plugin-target", "plugin-applied");',
      "    },",
      "  };",
      "}",
      "function Widget() {",
      "  return (",
      "    <main>",
      "      <span>{name}</span>",
      "      <span>{code}</span>",
      "      <span>plugin-target</span>",
      "    </main>",
      "  );",
      "}",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverOnly()] });",
      "}",
    ].join("\n");

    const html = await buildFromSource(source);

    expect(html).toContain("plugin-applied");
    expect(html).not.toContain("plugin-target");
    expect(html).toContain("display-name");
    expect(html).toContain("display-code");
  });

  it("uses the default empty plugin list", async () => {
    const html = await buildFromSource(
      'import { render } from "@belgie/render"; export default () => render({ widget: <main>plain</main> });',
    );

    expect(html).toContain("plain");
  });

  it("restores the process environment after a build", async () => {
    const environment = process.env;

    await buildFromSource(
      'import { render } from "@belgie/render"; export default () => render({ widget: <main>env</main> });',
    );

    expect(process.env).toBe(environment);
  });

  it("restores the process environment after concurrent builds", async () => {
    const source =
      'import { render } from "@belgie/render"; export default () => render({ widget: <main>env</main> });';
    const environment = process.env;
    const descriptor = Object.getOwnPropertyDescriptor(process, "env");

    await Promise.all([buildFromSource(source), buildFromSource(source)]);

    expect(process.env).toBe(environment);
    expect(Object.getOwnPropertyDescriptor(process, "env")).toStrictEqual(descriptor);
  });

  it("inlines CSS emitted by a client dependency", async () => {
    const source = [
      'import { render } from "@belgie/render";',
      'import "virtual:inline-style.css";',
      "export const run = () => render({ widget: <main>styled</main> });",
    ].join("\n");

    const html = await buildInlineWidget({ source, url: "file:///__deno_python_inline__.tsx", version: 1 }, [
      {
        name: "inline-style",
        resolveId(id) {
          return id === "virtual:inline-style.css" ? `\0${id}` : null;
        },
        load(id) {
          return id === "\0virtual:inline-style.css" ? ".card { color: rebeccapurple; }" : null;
        },
      },
    ]);

    expect(html).toContain(".card{color:#639}");
    expect(html.slice(0, html.indexOf("</head>"))).not.toContain("<link");
  });

  it("rejects invalid inputs and missing runtime context", async () => {
    await expect(render({ widget: "not an element" as never })).rejects.toThrow("widget must be a React element");
    await expect(render({ widget: createElement("main") })).rejects.toThrow("missing Belgie inline script context");

    installContext('import { render } from "@belgie/render"; export default () => render({ widget: <main /> });');
    await expect(render({ plugins: {} as never, widget: createElement("main") })).rejects.toThrow(
      "plugins must be an array",
    );
  });

  it.each([
    ["filesystem output", { name: "write", config: () => ({ build: { write: true } }) }, "filesystem output"],
    [
      "code splitting",
      { name: "chunks", config: () => ({ build: { rolldownOptions: { output: { codeSplitting: true } } } }) },
      "code splitting",
    ],
  ])("rejects plugin attempts to enable %s", async (_name, plugin, message) => {
    const source = 'import { render } from "@belgie/render"; export default () => render({ widget: <main /> });';
    await expect(
      buildInlineWidget({ source, url: "file:///__deno_python_inline__.tsx", version: 1 }, [plugin]),
    ).rejects.toThrow(message);
  });

  it("rejects non-CSS build assets", async () => {
    const source = 'import { render } from "@belgie/render"; export default () => render({ widget: <main /> });';
    await expect(
      buildInlineWidget({ source, url: "file:///__deno_python_inline__.tsx", version: 1 }, [
        {
          name: "asset",
          buildStart() {
            this.emitFile({ fileName: "secret.txt", source: "secret", type: "asset" });
          },
        },
      ]),
    ).rejects.toThrow("emitted non-CSS assets");
  });

  it("rejects computed plugin keys instead of shipping them to the browser", async () => {
    const source = [
      'import { render } from "@belgie/render";',
      'import serverOnly from "jsr:@example/server-plugin";',
      'const key = "plugins";',
      "export default () => render({ widget: <main />, [key]: [serverOnly()] });",
    ].join("\n");

    await expect(buildFromSource(source)).rejects.toThrow("statically analyzable render(...) options object");
  });

  it("instantiates plugins that import local helpers", async () => {
    const source = [
      'import { render } from "@belgie/render";',
      'import { makePlugin } from "./tests/fixtures/server-plugin.ts";',
      "function Widget() { return <main>fixture-target</main>; }",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [makePlugin()] });",
      "}",
    ].join("\n");

    const html = await buildFromSource(source);

    expect(html).toContain("fixture-applied");
    expect(html).not.toContain("fixture-target");
  });

  it("rejects jsr plugin imports during privileged evaluation", async () => {
    const source = [
      'import { render } from "@belgie/render";',
      'import serverOnly from "jsr:@example/server-plugin";',
      "export default () => render({ widget: <main />, plugins: [serverOnly()] });",
    ].join("\n");

    await expect(buildFromSource(source)).rejects.toThrow("plugin jsr: imports are not supported");
  });

  it("rejects non-string sealed sources", async () => {
    await expect(buildFromSource(1 as never)).rejects.toThrow("source must be a string");
  });

  it("rejects non-string inline module urls", async () => {
    await expect(
      buildFromSource(
        'import { render } from "@belgie/render"; export default () => render({ widget: <main /> });',
        1 as never,
      ),
    ).rejects.toThrow("url must be a string");
  });

  it("validates an explicit plugins array on the sentinel path", async () => {
    installContext(
      'import { render } from "@belgie/render"; export default () => render({ widget: <main />, plugins: [] });',
    );

    await expect(render({ widget: createElement("main"), plugins: [{ name: "noop" }] })).resolves.toStrictEqual(
      RENDER_REQUEST,
    );
  });

  it("restores a missing process.env descriptor after builds", async () => {
    const source =
      'import { render } from "@belgie/render"; export default () => render({ widget: <main>env</main> });';
    const descriptor = Object.getOwnPropertyDescriptor(process, "env");
    Reflect.deleteProperty(process, "env");
    try {
      await buildFromSource(source);
      expect("env" in process).toBeFalsy();
    } finally {
      if (descriptor !== undefined) {
        Object.defineProperty(process, "env", descriptor);
      }
    }
  });

  it("rejects plugins modules that do not evaluate to an array", async () => {
    await expect(
      buildFromSource(
        [
          'import { render } from "@belgie/render";',
          'const plugins = { name: "not-an-array" };',
          "export default () => render({ widget: <main />, plugins });",
        ].join("\n"),
      ),
    ).rejects.toThrow("plugins module must default-export an array");
  });

  it("rejects imported plugins modules that do not evaluate to an array", async () => {
    await expect(
      buildFromSource(
        [
          'import { render } from "@belgie/render";',
          'import { notAnArray } from "./tests/fixtures/not-array.ts";',
          "export default () => render({ widget: <main />, plugins: notAnArray });",
        ].join("\n"),
      ),
    ).rejects.toThrow("plugins module must default-export an array");
  });

  it("emits a plugins-only module for privileged evaluation", () => {
    const source = [
      'import { render } from "@belgie/render";',
      'const serverOnlyMarker = "server-only-plugin-marker";',
      "function serverPlugin() {",
      "  return { name: serverOnlyMarker };",
      "}",
      "function Widget() { return <main />; }",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverPlugin()] });",
      "}",
    ].join("\n");

    const moduleSource = preparePluginsModule(source);

    expect(moduleSource).toContain("serverOnlyMarker");
    expect(moduleSource).toContain("function serverPlugin()");
    expect(moduleSource).toContain("export default [serverPlugin()];");
    expect(moduleSource).not.toContain("function Widget");
    expect(moduleSource).not.toContain("export default function run");
  });

  it("ignores unrelated module bindings that share plugin property and parameter names", () => {
    const source = [
      'import { render } from "@belgie/render";',
      'const name = "display-name";',
      'const code = "display-code";',
      "function serverPlugin() {",
      "  return {",
      '    name: "server-only-plugin",',
      "    renderChunk(code) {",
      "      return code;",
      "    },",
      "  };",
      "}",
      "function Widget() { return <main>{name}{code}</main>; }",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverPlugin()] });",
      "}",
    ].join("\n");

    const moduleSource = preparePluginsModule(source);

    expect(moduleSource).toContain("function serverPlugin()");
    expect(moduleSource).toContain("export default [serverPlugin()];");
    expect(moduleSource).not.toContain('const name = "display-name"');
    expect(moduleSource).not.toContain('const code = "display-code"');
    expect(moduleSource).not.toContain("function Widget");
  });

  it("keeps class and nested plugin helpers without pulling unrelated name and code bindings", () => {
    const source = [
      'import { render } from "@belgie/render";',
      'const name = "display-name";',
      'const code = "display-code";',
      "const Base = class {};",
      "class MarkerPlugin extends Base {",
      '  renderChunk(code = "") {',
      '    return code.replace("x", "y");',
      "  }",
      "}",
      "function serverPlugin() {",
      '  const local = "server-only-plugin";',
      "  function build() {",
      "    return new MarkerPlugin();",
      "  }",
      "  return Object.assign(build(), { name: local });",
      "}",
      "function Widget() { return <main>{name}{code}</main>; }",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverPlugin()] });",
      "}",
    ].join("\n");

    const moduleSource = preparePluginsModule(source);

    expect(moduleSource).toContain("class MarkerPlugin extends Base");
    expect(moduleSource).toContain("function serverPlugin()");
    expect(moduleSource).toContain("const Base = class {}");
    expect(moduleSource).toContain("export default [serverPlugin()];");
    expect(moduleSource).not.toContain('const name = "display-name"');
    expect(moduleSource).not.toContain('const code = "display-code"');
    expect(moduleSource).not.toContain("function Widget");
  });

  it("keeps module bindings referenced only in parameter defaults", () => {
    const source = [
      'import { render } from "@belgie/render";',
      'const name = "display-name";',
      'const code = "display-code";',
      'const serverOnlyMarker = "server-only-plugin-marker";',
      'const computedKey = "value";',
      "class MarkerPlugin {",
      "  renderChunk(",
      "    { code = serverOnlyMarker, [computedKey]: nested = serverOnlyMarker, ...rest } = {",
      "      code: serverOnlyMarker,",
      "    },",
      "    [item = serverOnlyMarker] = [],",
      "  ) {",
      "    return code + nested + String(rest) + item;",
      "  }",
      "}",
      "function serverPlugin() {",
      "  return new MarkerPlugin();",
      "}",
      "function Widget() { return <main>{name}{code}</main>; }",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverPlugin()] });",
      "}",
    ].join("\n");

    const moduleSource = preparePluginsModule(source);

    expect(moduleSource).toContain('const serverOnlyMarker = "server-only-plugin-marker"');
    expect(moduleSource).toContain('const computedKey = "value"');
    expect(moduleSource).toContain("class MarkerPlugin");
    expect(moduleSource).toContain("function serverPlugin()");
    expect(moduleSource).toContain("export default [serverPlugin()];");
    expect(moduleSource).not.toContain('const name = "display-name"');
    expect(moduleSource).not.toContain('const code = "display-code"');
    expect(moduleSource).not.toContain("function Widget");
  });

  it("preserves npm plugin imports in the privileged module", () => {
    const moduleSource = preparePluginsModule(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "export default () => render({ widget: <main />, plugins: [serverPlugin()] });",
      ].join("\n"),
    );

    expect(moduleSource).toContain('import serverPlugin from "npm:plugin-package@1.2.3";');
    expect(moduleSource).toContain("export default [serverPlugin()];");
  });

  it("skips empty and missing plugin lists when preparing modules", () => {
    expect(
      preparePluginsModule(
        'import { render } from "@belgie/render"; export default () => render({ widget: <main /> });',
      ),
    ).toBeUndefined();
    expect(
      preparePluginsModule(
        'import { render } from "@belgie/render"; export default () => render({ widget: <main />, plugins: [] });',
      ),
    ).toBeUndefined();
  });

  it("keeps export-stripped plugin helpers in the privileged module", () => {
    const moduleSource = preparePluginsModule(
      [
        'import { render } from "@belgie/render";',
        'export function serverPlugin() { return { name: "exported" }; }',
        "export default () => render({ widget: <main />, plugins: [serverPlugin()] });",
      ].join("\n"),
    );

    expect(moduleSource).toContain("function serverPlugin()");
    expect(moduleSource).not.toContain("export function serverPlugin");
    expect(moduleSource).toContain("export default [serverPlugin()];");
  });

  it("rejects mutated plugin arrays when preparing modules", () => {
    expect(() =>
      preparePluginsModule(
        [
          'import { render } from "@belgie/render";',
          'function serverPlugin() { return { name: "push" }; }',
          "const plugins = [];",
          "plugins.push(serverPlugin());",
          "export default () => render({ widget: <main />, plugins });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects setup calls that mutate plugin bindings when preparing modules", () => {
    expect(() =>
      preparePluginsModule(
        [
          'import { render } from "@belgie/render";',
          'function serverPlugin() { return { name: "setup" }; }',
          "function setup(target) { target.push(serverPlugin()); }",
          "const plugins = [];",
          "setup(plugins);",
          "export default () => render({ widget: <main />, plugins });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });
});
