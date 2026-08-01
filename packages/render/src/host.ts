import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { cwd } from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

import type { PluginOption } from "vite";
import { createServer } from "vite";

import type { RenderContext } from "./build.js";
import { buildInlineWidget } from "./build.js";
import { normalizeNpmSpecifier, preparePluginsModule } from "./source.js";

const require = createRequire(import.meta.url);
const PACKAGE_ROOT = dirname(import.meta.dirname);
const BUILD_ENVIRONMENT_SEED: Record<string, string> = {
  APPVEYOR: "1",
  NODE_ENV: "production",
  TERM: "dumb",
};
const INLINE_MODULE_FILENAME = "__deno_python_inline__.tsx";
const PLUGINS_ENTRY_ID = "virtual:belgie-render/plugins";

function defaultInlineSourceUrl(): string {
  return pathToFileURL(join(cwd(), INLINE_MODULE_FILENAME)).href;
}

const renderLock: { gate: Promise<void> } = { gate: Promise.resolve() };

async function withBuildLock<T>(build: () => Promise<T>): Promise<T> {
  let release!: () => void;
  const previous = renderLock.gate;
  renderLock.gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await previous;

  const processEnvironment = Object.getOwnPropertyDescriptor(process, "env");
  Object.defineProperty(process, "env", {
    configurable: true,
    value: { ...BUILD_ENVIRONMENT_SEED },
  });
  // Patch the CJS os export (ESM namespace bindings are immutable). Cosmiconfig stopDir
  // Otherwise walks from /tmp workspaces toward the real home and can touch /etc.
  const os = require("node:os") as typeof import("node:os");
  const previousHomedir = Object.getOwnPropertyDescriptor(os, "homedir")!;
  Object.defineProperty(os, "homedir", {
    configurable: true,
    enumerable: true,
    value: () => PACKAGE_ROOT,
  });
  try {
    return await build();
  } finally {
    Object.defineProperty(os, "homedir", previousHomedir);
    if (processEnvironment === undefined) {
      Reflect.deleteProperty(process, "env");
    } else {
      Object.defineProperty(process, "env", processEnvironment);
    }
    release();
  }
}

async function instantiatePluginsFromSource(source: string, url: string): Promise<PluginOption[]> {
  const moduleSource = preparePluginsModule(source);
  if (moduleSource === undefined) {
    return [];
  }

  const server = await createServer({
    appType: "custom",
    configFile: false,
    envDir: false,
    logLevel: "silent",
    optimizeDeps: { noDiscovery: true },
    plugins: [
      {
        name: "belgie-render-plugins",
        async resolveId(id, importer) {
          // Resolve as the inline module URL so relative imports use the workspace, like Deno.
          if (id === PLUGINS_ENTRY_ID) {
            return url;
          }
          // Absolute paths keep Deno allow_read checks on the workspace root (not "./…").
          if (importer === url && (id.startsWith("./") || id.startsWith("../"))) {
            return fileURLToPath(new URL(id, url));
          }
          if (id.startsWith("jsr:")) {
            throw new Error(`@belgie/render: plugin jsr: imports are not supported: ${id}`);
          }
          const normalized = normalizeNpmSpecifier(id);
          if (normalized !== undefined) {
            return this.resolve(normalized, importer, { skipSelf: true });
          }
          return null;
        },
        load(id) {
          return id === url ? moduleSource : null;
        },
      },
    ],
    root: PACKAGE_ROOT,
    server: { hmr: false, middlewareMode: true, ws: false },
  });
  try {
    const loaded = await server.ssrLoadModule(PLUGINS_ENTRY_ID);
    const plugins = (loaded as { default?: unknown }).default;
    if (!Array.isArray(plugins)) {
      throw new TypeError("@belgie/render: plugins module must default-export an array");
    }
    return plugins as PluginOption[];
  } finally {
    await server.close();
  }
}

export async function buildFromSource(source: string, url: string = defaultInlineSourceUrl()): Promise<string> {
  if (typeof source !== "string") {
    throw new TypeError("@belgie/render: source must be a string");
  }
  if (typeof url !== "string") {
    throw new TypeError("@belgie/render: url must be a string");
  }
  return withBuildLock(async () => {
    const context: RenderContext = {
      source,
      url,
      version: 1,
    };
    const plugins = await instantiatePluginsFromSource(source, url);
    return buildInlineWidget(context, plugins);
  });
}

export default buildFromSource;
