import { describe, expect, test, vi } from "vitest";
import type { ResolvedConfig, Rollup } from "vite";

import { invariantPlugin, readHtml } from "../src/build.ts";

function config(options: { configFile?: string; output?: unknown; write?: boolean } = {}): ResolvedConfig {
  return {
    build: {
      rolldownOptions: {
        output: ("output" in options ? options.output : { codeSplitting: false }) as never,
      },
      write: options.write ?? false,
    },
    configFile: options.configFile,
  } as unknown as ResolvedConfig;
}

describe("build invariants", () => {
  test.each([
    ["config files", config({ configFile: "/vite.config.ts" }), "configuration files"],
    ["filesystem writes", config({ write: true }), "filesystem output"],
    ["output arrays", config({ output: [{ codeSplitting: false }] }), "code splitting"],
    ["missing output", config({ output: null }), "code splitting"],
  ])("rejects %s", (_name, resolved, message) => {
    const hook = invariantPlugin().configResolved;
    if (typeof hook !== "function") {
      throw new Error("expected configResolved hook");
    }
    expect(() => hook.call({} as never, resolved)).toThrow(message);
  });

  test("reads string and byte HTML assets", () => {
    const stringOutput = {
      output: [{ fileName: "widget.html", names: [], needsCodeReference: false, originalFileName: null, originalFileNames: [], source: "html", type: "asset" }],
    } as unknown as Rollup.RollupOutput;
    const byteOutput = {
      output: [{ fileName: "widget.html", names: [], needsCodeReference: false, originalFileName: null, originalFileNames: [], source: new TextEncoder().encode("bytes"), type: "asset" }],
    } as unknown as Rollup.RollupOutput;

    expect(readHtml(stringOutput)).toBe("html");
    expect(readHtml([byteOutput])).toBe("bytes");
  });

  test("rejects missing and unexpected final artifacts", () => {
    expect(() => readHtml({ output: [] } as unknown as Rollup.RollupOutput)).toThrow("expected one HTML artifact");
    expect(() => readHtml({ output: [{ fileName: "widget.js", type: "chunk" }] } as unknown as Rollup.RollupOutput)).toThrow(
      "expected widget.html",
    );
  });

  test("replaces the build bundle with one HTML asset", () => {
    const plugin = invariantPlugin();
    const hook = plugin.generateBundle;
    if (typeof hook !== "object" || typeof hook.handler !== "function") {
      throw new Error("expected generateBundle hook");
    }
    const bundle = {
      "entry.js": {
        code: "console.log('widget')",
        dynamicImports: [],
        exports: [],
        facadeModuleId: "entry",
        fileName: "entry.js",
        implicitlyLoadedBefore: [],
        importedBindings: {},
        imports: [],
        isDynamicEntry: false,
        isEntry: true,
        isImplicitEntry: false,
        map: null,
        moduleIds: [],
        modules: {},
        name: "entry",
        preliminaryFileName: "entry.js",
        referencedFiles: [],
        sourcemapFileName: null,
        type: "chunk",
      },
    };
    const emitFile = vi.fn();

    hook.handler.call({ emitFile } as never, {} as never, bundle as never, false);

    expect(bundle).toEqual({});
    expect(emitFile).toHaveBeenCalledWith(expect.objectContaining({ fileName: "widget.html", type: "asset" }));
  });
});
