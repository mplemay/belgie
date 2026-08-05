import { readFileSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { pathToFileURL } from "node:url";

// Must load before vite so rolldown's requireNative libc probe hits the sanitized report.
import "./process-report.js";

import type { Plugin, PluginOption, Rollup } from "vite";

import { buildVirtualEntry, renderBundle } from "./html.js";
import { hasDefaultExport } from "./validate-widget.js";

const PACKAGE_ROOT = dirname(import.meta.dirname);
const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;
const CLIENT_ENTRY_ID = "virtual:belgie-vite/client-entry";
const RESOLVED_CLIENT_ENTRY_ID = `\0${CLIENT_ENTRY_ID}`;

export function invariantPlugin(): Plugin {
  return {
    name: "belgie-vite-invariants",
    enforce: "post",
    configResolved(config) {
      if (config.configFile !== undefined) {
        throw new Error("@belgie/vite: Vite configuration files are disabled");
      }
      if (config.build.write) {
        throw new Error("@belgie/vite: plugins cannot enable filesystem output");
      }
      const output = config.build.rolldownOptions.output;
      if (Array.isArray(output) || output?.codeSplitting !== false) {
        throw new Error("@belgie/vite: plugins cannot enable code splitting");
      }
    },
    generateBundle: {
      order: "post",
      handler(_options, bundle) {
        const html = renderBundle(bundle);
        for (const fileName of Object.keys(bundle)) {
          delete bundle[fileName];
        }
        this.emitFile({ fileName: "widget.html", source: html, type: "asset" });
      },
    },
  };
}

export function readHtml(output: Rollup.RollupOutput | Rollup.RollupOutput[]): string {
  const outputs = Array.isArray(output) ? output : [output];
  const artifacts = outputs.flatMap((result) => result.output);
  if (artifacts.length !== 1) {
    throw new Error(`@belgie/vite: expected one HTML artifact, received ${artifacts.length}`);
  }
  const [artifact] = artifacts;
  if (artifact?.type !== "asset" || artifact.fileName !== "widget.html") {
    throw new Error(`@belgie/vite: expected widget.html, received ${artifact?.fileName ?? "nothing"}`);
  }
  return typeof artifact.source === "string" ? artifact.source : new TextDecoder().decode(artifact.source);
}

function createWidgetFilePlugin(widgetPath: string): Plugin {
  const entrySource = buildVirtualEntry(widgetPath);
  return {
    name: "belgie-vite-widget-file",
    resolveId(id) {
      if (id === CLIENT_ENTRY_ID) {
        return RESOLVED_CLIENT_ENTRY_ID;
      }
      return null;
    },
    load(id) {
      if (id === RESOLVED_CLIENT_ENTRY_ID) {
        return entrySource;
      }
      return null;
    },
  };
}

export async function buildWidgetFile(widgetPath: string, plugins: PluginOption[] = []): Promise<string> {
  const absolutePath = isAbsolute(widgetPath) ? widgetPath : resolve(widgetPath);
  const source = readFileSync(absolutePath, "utf8");
  if (!hasDefaultExport(source)) {
    throw new Error(`@belgie/vite: widget file missing a default export: ${absolutePath}`);
  }

  const processEnvironment = Object.getOwnPropertyDescriptor(process, "env");
  Object.defineProperty(process, "env", {
    configurable: true,
    value: { ...(processEnvironment?.value as Record<string, string> | undefined), NODE_ENV: "production" },
  });
  try {
    const [{ default: react }, { build }] = await Promise.all([import("@vitejs/plugin-react"), import("vite")]);
    const output = await build({
      appType: "custom",
      configFile: false,
      envDir: false,
      logLevel: "silent",
      mode: "production",
      plugins: [createWidgetFilePlugin(absolutePath), react(), ...plugins, invariantPlugin()],
      publicDir: false,
      resolve: { dedupe: ["react", "react-dom"] },
      root: PACKAGE_ROOT,
      build: {
        assetsInlineLimit: MAX_INLINE_ASSET_SIZE,
        copyPublicDir: false,
        cssCodeSplit: false,
        emptyOutDir: false,
        license: false,
        manifest: false,
        modulePreload: false,
        reportCompressedSize: false,
        sourcemap: false,
        ssrManifest: false,
        watch: null,
        write: false,
        rolldownOptions: {
          input: CLIENT_ENTRY_ID,
          output: { codeSplitting: false },
        },
      },
    });
    return readHtml(output as Rollup.RollupOutput | Rollup.RollupOutput[]);
  } finally {
    if (processEnvironment === undefined) {
      Reflect.deleteProperty(process, "env");
    } else {
      Object.defineProperty(process, "env", processEnvironment);
    }
  }
}

export function packageNameFromSpecifier(specifier: string): string {
  const value = specifier.startsWith("npm:") ? specifier.slice("npm:".length) : specifier;
  if (value.startsWith("jsr:")) {
    throw new Error(`@belgie/vite: plugin jsr: imports are not supported: ${specifier}`);
  }
  const pattern = value.startsWith("@") ? /^(@[^/]+\/[^@/]+)(?:@.*)?$/u : /^([^@/]+)(?:@.*)?$/u;
  const match = pattern.exec(value);
  if (match?.[1] !== undefined) {
    return match[1];
  }
  throw new Error(`@belgie/vite: invalid plugin specifier: ${specifier}`);
}

export async function loadVitePlugins(specifiers: string[]): Promise<PluginOption[]> {
  const plugins: PluginOption[] = [];
  for (const specifier of specifiers) {
    const name = packageNameFromSpecifier(specifier);
    let imported: unknown;
    try {
      imported = await import(name);
    } catch (error) {
      try {
        const { createRequire } = await import("node:module");
        const require = createRequire(resolve(process.cwd(), "package.json"));
        const resolved = pathToFileURL(require.resolve(name)).href;
        imported = await import(resolved);
      } catch {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`@belgie/vite: failed to load plugin ${specifier}: ${message}`);
      }
    }
    const candidate = (imported as { default?: unknown }).default ?? imported;
    if (typeof candidate === "function") {
      plugins.push((candidate as () => PluginOption)());
    } else {
      plugins.push(candidate as PluginOption);
    }
  }
  return plugins;
}
