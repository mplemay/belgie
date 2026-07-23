import {
  CLIENT_RENDER_ID,
  createInlineSourcePlugin,
  normalizeNpmSpecifier,
  prepareBrowserCaller,
  stripServerPlugins,
  WIDGET_EXPORT_NAME,
} from "../src/source.ts";

describe("inline source transform", () => {
  it("removes the plugins expression and imports used only by plugins", () => {
    const source = [
      'import { render } from "npm:@belgie/render";',
      'import serverPlugin, { browserValue, serverHelper } from "npm:plugin-package@1.2.3";',
      "const Widget = () => <main>{browserValue}</main>;",
      "export default function run() {",
      "  return render({ widget: <Widget />, plugins: [serverPlugin(), serverHelper()] });",
      "}",
    ].join("\n");

    const transformed = stripServerPlugins(source);

    expect(transformed).not.toContain("plugins:");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).not.toContain("serverHelper");
    expect(transformed).toContain('import { browserValue } from "npm:plugin-package@1.2.3";');
    expect(transformed).toContain("widget: <Widget />");
  });

  it("removes plugins when render is imported as the default binding", () => {
    const transformed = stripServerPlugins(
      [
        'import render from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "export default () => render({ widget: <main />, plugins: [serverPlugin()] });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins:");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).not.toContain("npm:plugin-package@1.2.3");
    expect(transformed).toContain("widget: <main />");
  });

  it("leaves source without a server plugins property unchanged", () => {
    const source = 'import { render } from "@belgie/render"; export default () => render({ widget: <main /> });';
    expect(stripServerPlugins(source)).toBe(source);
  });

  it("removes first and only plugin properties and whole plugin imports", () => {
    const first = stripServerPlugins(
      [
        'import { render as inlineRender } from "@belgie/render@0.1.0";',
        'import * as server from "jsr:@example/plugin";',
        'import keep from "npm:keep@1.0.0";',
        "export default () => inlineRender({ plugins: [server.plugin()], widget: <main>{keep}</main> });",
      ].join("\n"),
    );
    const only = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import server from "jsr:@example/plugin";',
        "export default () => render({ plugins: [server()] });",
      ].join("\n"),
    );

    expect(first).not.toContain("jsr:@example/plugin");
    expect(first).toContain('import keep from "npm:keep@1.0.0";');
    expect(first).toContain("widget: <main>{keep}</main>");
    expect(only).toContain("render({  })");
  });

  it("retains default and namespace browser imports from mixed declarations", () => {
    const transformed = stripServerPlugins(
      [
        'import renderDefault, { render } from "@belgie/render";',
        'import keepDefault, { serverHelper } from "npm:mixed-default@1.0.0";',
        'import serverFactory, * as browserNamespace from "npm:mixed-namespace@1.0.0";',
        "export default () => render({",
        '  "plugins": [serverHelper(), serverFactory()],',
        "  widget: <main>{keepDefault}{browserNamespace.value}</main>,",
        "});",
        "export const afterRender = () => renderDefault({ widget: <main /> });",
      ].join("\n"),
    );

    expect(transformed).toContain('import keepDefault from "npm:mixed-default@1.0.0";');
    expect(transformed).toContain('import * as browserNamespace from "npm:mixed-namespace@1.0.0";');
    expect(transformed).not.toContain("serverHelper");
    expect(transformed).not.toContain("serverFactory");
    expect(transformed).toContain("afterRender = () => renderDefault({ widget: <main /> })");
  });

  it("removes plugins from a variable options object with satisfies", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const options = { plugins: [serverPlugin()], widget: <main /> } satisfies { plugins: unknown[]; widget: unknown };",
        "export default () => render(options);",
      ].join("\n"),
    );

    expect(transformed).toContain("const options = { widget: <main /> } satisfies");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).not.toContain("npm:plugin-package@1.2.3");
    expect(transformed).toContain("render(options)");
  });

  it("removes a plugins array binding and its import", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const plugins = [serverPlugin()];",
        "export default () => render({ widget: <main />, plugins });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).not.toContain("npm:plugin-package@1.2.3");
    expect(transformed).toContain("widget: <main />");
  });

  it("removes chained plugin-only bindings", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const factory = serverPlugin;",
        "const plugins = [factory()];",
        "export default () => render({ widget: <main />, plugins });",
      ].join("\n"),
    );
    const sameDeclaration = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const factory = serverPlugin, plugins = [factory()];",
        "export default () => render({ widget: <main />, plugins });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("factory");
    expect(transformed).not.toContain("plugins");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).not.toContain("npm:plugin-package@1.2.3");
    expect(transformed).toContain("widget: <main />");
    expect(sameDeclaration).not.toContain("factory");
    expect(sameDeclaration).not.toContain("const ");
    expect(sameDeclaration).toContain("widget: <main />");
  });

  it("removes plugin declarators from mixed variable declarations", () => {
    const first = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const plugins = [serverPlugin()], keep = 1;",
        "export default () => render({ widget: <main>{keep}</main>, plugins });",
      ].join("\n"),
    );
    const last = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const keep = 1, plugins = [serverPlugin()];",
        "export default () => render({ widget: <main>{keep}</main>, plugins });",
      ].join("\n"),
    );

    expect(first).toContain("const keep = 1;");
    expect(first).not.toContain("serverPlugin");
    expect(first).toContain("{keep}");
    expect(last).toContain("const keep = 1;");
    expect(last).not.toContain("plugins");
    expect(last).not.toContain("npm:plugin-package@1.2.3");
  });

  it("rejects plugins bindings that escape into other code", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "const plugins = [serverPlugin()];",
          "console.log(plugins);",
          "export default () => render({ widget: <main />, plugins });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects exported plugins bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "export const plugins = [serverPlugin()];",
          "export default () => render({ widget: <main />, plugins });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects plugins bindings re-exported by specifier", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "const plugins = [serverPlugin()];",
          "export { plugins };",
          "export default () => render({ widget: <main />, plugins });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects destructured plugins bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "const [plugins] = [[serverPlugin()]];",
          "export default () => render({ widget: <main />, plugins });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("removes plugins carried by an object spread", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const server = { plugins: [serverPlugin()] };",
        "export default () => render({ widget: <main />, ...server });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins:");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain("...server");
    expect(transformed).toContain("widget: <main />");
  });

  it("removes plugins when render is called through a namespace import", () => {
    const transformed = stripServerPlugins(
      [
        'import * as R from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "export default () => R.render({ widget: <main />, plugins: [serverPlugin()] });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins:");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain("R.render({ widget: <main /> })");
  });

  it("rejects dynamically produced render options", () => {
    expect(() =>
      stripServerPlugins(
        ['import { render } from "@belgie/render";', "export default () => render(getOptions());"].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects opaque object spreads in render options", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          "declare const cfg: Record<string, unknown>;",
          "export default () => render({ widget: <main />, ...cfg });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects reassigned options bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          "let options = { widget: <main /> };",
          "options = { widget: <main /> };",
          "export default () => render(options);",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects property assignment on options bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "const options = { widget: <main /> };",
          "options.plugins = [serverPlugin()];",
          "export default () => render(options);",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects mutating method calls on options bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "const options = { plugins: [], widget: <main /> };",
          "options.plugins.push(serverPlugin());",
          "export default () => render(options);",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects update expressions on options bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          "const options = { widget: <main />, n: 0 };",
          "options.n++;",
          "export default () => render(options);",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects nested property writes on options bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "const options = { meta: {}, widget: <main /> };",
          "options.meta.plugins = [serverPlugin()];",
          "export default () => render(options);",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects render calls without options", () => {
    expect(() =>
      stripServerPlugins(['import { render } from "@belgie/render";', "export default () => render();"].join("\n")),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects nested opaque spreads through bound objects", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          "declare const cfg: Record<string, unknown>;",
          "const deep = { ...cfg };",
          "const mid = { ...deep };",
          "export default () => render({ widget: <main />, ...mid });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("strips plugins through cyclic object spreads", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const a = { ...b };",
        "const b = { plugins: [serverPlugin()], ...a };",
        "export default () => render({ widget: <main />, ...a });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain("widget: <main />");
  });

  it("strips plugins from parenthesized and type-asserted options", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "export default () => render(({ plugins: [serverPlugin()], widget: <main /> } as { widget: unknown }));",
      ].join("\n"),
    );

    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain("widget: <main />");
  });

  it("strips plugins through a simple render alias", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const r = render;",
        "export default () => r({ widget: <main />, plugins: [serverPlugin()] });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins:");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain("r({ widget: <main /> })");
  });

  it("strips plugins through chained render aliases and parenthesized callees", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const r = render;",
        "const s = r;",
        "export default () => (s)({ widget: <main />, plugins: [serverPlugin()] });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins:");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain("(s)({ widget: <main /> })");
  });

  it("strips plugins through a namespace render alias", () => {
    const transformed = stripServerPlugins(
      [
        'import * as R from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "const r = R.render;",
        "export default () => r({ widget: <main />, plugins: [serverPlugin()] });",
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins:");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain("r({ widget: <main /> })");
  });

  it("rejects dynamic import of render", () => {
    expect(() =>
      stripServerPlugins(
        [
          'const mod = await import("@belgie/render");',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "export default () => mod.render({ widget: <main />, plugins: [serverPlugin()] });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects npm dynamic import of render", () => {
    expect(() =>
      stripServerPlugins(
        [
          'const mod = await import("npm:@belgie/render");',
          "export default () => mod.render({ widget: <main /> });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects escaped render bindings", () => {
    expect(() =>
      stripServerPlugins(['import { render } from "@belgie/render";', "export default () => foo(render);"].join("\n")),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects exported render bindings", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          "export { render };",
          "export default () => render({ widget: <main /> });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects reassigned render aliases", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "let r = render;",
          "r = undefined!;",
          "export default () => r({ widget: <main />, plugins: [serverPlugin()] });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects updated render aliases", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          "let r = render as unknown as number;",
          "r++;",
          "export default () => (r as unknown as typeof render)({ widget: <main /> });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects optional render calls", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "export default () => render?.({ widget: <main />, plugins: [serverPlugin()] });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects computed plugin keys", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          'const key = "plugins";',
          "export default () => render({ widget: <main />, [key]: [serverPlugin()] });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects computed plugin key expressions", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          'export default () => render({ widget: <main />, ["plug" + "ins"]: [serverPlugin()] });',
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("rejects computed plugin keys inside static spreads", () => {
    expect(() =>
      stripServerPlugins(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          'const key = "plugins";',
          "const server = { [key]: [serverPlugin()] };",
          "export default () => render({ widget: <main />, ...server });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options object");
  });

  it("strips computed string-literal plugin keys", () => {
    const transformed = stripServerPlugins(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        'export default () => render({ ["widget"]: <main />, ["plugins"]: [serverPlugin()] });',
      ].join("\n"),
    );

    expect(transformed).not.toContain("plugins");
    expect(transformed).not.toContain("serverPlugin");
    expect(transformed).toContain('["widget"]: <main />');
  });

  it("prepares a browser caller that exports the extracted widget", () => {
    const prepared = prepareBrowserCaller(
      [
        'import { render } from "@belgie/render";',
        'import serverPlugin from "npm:plugin-package@1.2.3";',
        "function Widget() { return <main />; }",
        "export default function run() {",
        "  return render({ widget: <Widget />, plugins: [serverPlugin()] });",
        "}",
      ].join("\n"),
    );

    expect(prepared).not.toContain("serverPlugin");
    expect(prepared).not.toContain("plugins:");
    expect(prepared).toContain(`export const ${WIDGET_EXPORT_NAME} = <Widget />`);
  });

  it("rejects run-local widget bindings", () => {
    expect(() =>
      prepareBrowserCaller(
        [
          'import { render } from "@belgie/render";',
          "export default function run() {",
          '  const label = "hello";',
          "  return render({ widget: <main>{label}</main> });",
          "}",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options expression");
  });

  it("rejects missing widget properties for the browser caller", () => {
    expect(() =>
      prepareBrowserCaller(
        [
          'import { render } from "@belgie/render";',
          'import serverPlugin from "npm:plugin-package@1.2.3";',
          "export default () => render({ plugins: [serverPlugin()] });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options expression");
  });

  it("rejects conflicting widget expressions across render calls", () => {
    expect(() =>
      prepareBrowserCaller(
        [
          'import { render } from "@belgie/render";',
          "export default function run() {",
          "  void render({ widget: <main>one</main> });",
          "  return render({ widget: <main>two</main> });",
          "}",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options expression");
  });

  it("rejects a predeclared widget export binding", () => {
    expect(() =>
      prepareBrowserCaller(
        [
          'import { render } from "@belgie/render";',
          `const ${WIDGET_EXPORT_NAME} = null;`,
          "export default () => render({ widget: <main /> });",
        ].join("\n"),
      ),
    ).toThrow("statically analyzable render(...) options expression");
  });

  it("allows module-level member access and type assertions in widget expressions", () => {
    const prepared = prepareBrowserCaller(
      [
        'import { render } from "@belgie/render";',
        "const props = { value: 'ok' };",
        "export default () => render({ widget: (<main>{props.value}</main> as unknown) });",
      ].join("\n"),
    );

    expect(prepared).toContain("props.value");
    expect(prepared).toContain("as unknown");
    expect(prepared).toContain(`export const ${WIDGET_EXPORT_NAME}`);
  });

  it("extracts widgets from exported class components", () => {
    const prepared = prepareBrowserCaller(
      [
        'import { render } from "@belgie/render";',
        "export class Widget { view() { return <main />; } }",
        "export default () => render({ widget: <Widget /> });",
      ].join("\n"),
    );

    expect(prepared).toContain(`export const ${WIDGET_EXPORT_NAME} = <Widget />`);
  });

  it.each([
    ["npm:react@19.2.6", "react"],
    ["npm:react-dom@19.2.6/client", "react-dom/client"],
    ["npm:@scope/package@2.0.0", "@scope/package"],
    ["npm:@scope/package@2.0.0/subpath", "@scope/package/subpath"],
    ["react", undefined],
  ])("normalizes %s", (specifier, expected) => {
    expect(normalizeNpmSpecifier(specifier)).toBe(expected);
  });

  it("rejects malformed npm specifiers", () => {
    expect(() => normalizeNpmSpecifier("npm:@scope")).toThrow("invalid npm specifier");
  });

  it("resolves and loads the complete virtual browser module graph", async () => {
    const source = [
      'import { render } from "@belgie/render";',
      "export default () => render({ widget: <main>graph</main> });",
    ].join("\n");
    const plugin = createInlineSourcePlugin({ source, url: "file:///caller.tsx", version: 1 });
    const load = plugin.load;
    const resolve = plugin.resolveId;
    if (typeof load !== "function" || typeof resolve !== "function") {
      throw new Error("expected load and resolve hooks");
    }
    const context = { resolve: async (id: string) => ({ id }) };
    const entryId = (await resolve.call(context, "virtual:belgie-render/client-entry", undefined, {})) as string | null;
    const callerId = (await resolve.call(context, "virtual:belgie-render/caller", undefined, {})) as string | null;
    const apiId = (await resolve.call(context, CLIENT_RENDER_ID, undefined, {})) as string | null;
    const packageApiId = (await resolve.call(context, "npm:@belgie/render@0.1.0", undefined, {})) as string | null;
    const npmId = (await resolve.call(context, "npm:react@19.2.6", undefined, {})) as {
      id: string;
    } | null;
    const unknownId = (await resolve.call(context, "unknown", undefined, {})) as string | null;
    const entrySource = load.call({}, String(entryId)) as string;
    const callerSource = load.call({}, String(callerId)) as string;
    const apiSource = load.call({}, String(apiId)) as string;

    expect(entrySource).toContain("StrictMode");
    expect(entrySource).toContain("createRoot");
    expect(entrySource).toContain(WIDGET_EXPORT_NAME);
    expect(entrySource).not.toContain("await run()");
    expect(entrySource).not.toContain("assertRenderDefinition");
    expect(callerSource).toContain(`export const ${WIDGET_EXPORT_NAME} = <main>graph</main>`);
    expect(apiSource).toContain("render cannot be called from the browser module graph");
    expect(apiSource).not.toContain("assertRenderDefinition");
    expect(packageApiId).toBe(apiId);
    expect(npmId).toStrictEqual({ id: "react" });
    expect(unknownId).toBeNull();
    expect(load.call({}, "unknown")).toBeNull();
    await expect(resolve.call(context, "jsr:@retained/browser", undefined, {})).rejects.toThrow(
      "retained browser import",
    );
  });
});
