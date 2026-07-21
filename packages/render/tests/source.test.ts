import {
  CLIENT_RENDER_ID,
  createInlineSourcePlugin,
  normalizeNpmSpecifier,
  stripServerPlugins,
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
        "export const afterRender = renderDefault;",
      ].join("\n"),
    );

    expect(transformed).toContain('import keepDefault from "npm:mixed-default@1.0.0";');
    expect(transformed).toContain('import * as browserNamespace from "npm:mixed-namespace@1.0.0";');
    expect(transformed).not.toContain("serverHelper");
    expect(transformed).not.toContain("serverFactory");
    expect(transformed).toContain("afterRender = renderDefault");
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
    const plugin = createInlineSourcePlugin({ source: "export {};", url: "file:///caller.tsx", version: 1 });
    const load = plugin.load;
    const resolve = plugin.resolveId;
    if (typeof load !== "function" || typeof resolve !== "function") {
      throw new Error("expected load and resolve hooks");
    }
    const context = { resolve: async (id: string) => ({ id }) };
    const entryId = (await resolve.call(
      context as never,
      "virtual:belgie-render/client-entry",
      undefined,
      {} as never,
    )) as string | null;
    const callerId = (await resolve.call(context as never, "virtual:belgie-render/caller", undefined, {} as never)) as
      | string
      | null;
    const apiId = (await resolve.call(context as never, CLIENT_RENDER_ID, undefined, {} as never)) as string | null;
    const packageApiId = (await resolve.call(context as never, "npm:@belgie/render@0.1.0", undefined, {} as never)) as
      | string
      | null;
    const npmId = (await resolve.call(context as never, "npm:react@19.2.6", undefined, {} as never)) as {
      id: string;
    } | null;
    const unknownId = (await resolve.call(context as never, "unknown", undefined, {} as never)) as string | null;
    const entrySource = load.call({} as never, String(entryId)) as string;
    const callerSource = load.call({} as never, String(callerId)) as string;
    const apiSource = load.call({} as never, String(apiId)) as string;

    expect(entrySource).toContain("StrictMode");
    expect(entrySource).toContain("createRoot");
    expect(callerSource).toBe("export {};");
    expect(apiSource).toContain("@belgie/render/client-definition");
    expect(apiSource).toContain("assertRenderDefinition");
    expect(packageApiId).toBe(apiId);
    expect(npmId).toStrictEqual({ id: "react" });
    expect(unknownId).toBeNull();
    expect(load.call({} as never, "unknown")).toBeNull();
    await expect(resolve.call(context as never, "jsr:@retained/browser", undefined, {} as never)).rejects.toThrow(
      "retained browser import",
    );
  });
});
