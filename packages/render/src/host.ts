import { dirname } from "node:path";

import type { PluginOption } from "vite";
import { createServer } from "vite";

import type { RenderContext } from "./build.js";
import { buildInlineWidget } from "./build.js";
import { preparePluginsModule } from "./source.js";

const PACKAGE_ROOT = dirname(import.meta.dirname);
const BUILD_ENVIRONMENT_SEED: Record<string, string> = {
  APPVEYOR: "1",
  NODE_ENV: "production",
  TERM: "dumb",
};
const INLINE_SOURCE_URL = "file:///__deno_python_inline__.tsx";
const PLUGINS_VIRTUAL_ID = "virtual:belgie-render/plugins";
const RESOLVED_PLUGINS_VIRTUAL_ID = `\0${PLUGINS_VIRTUAL_ID}`;

function createBuildEnvironment(): Record<string, string> {
  return { ...BUILD_ENVIRONMENT_SEED };
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
    value: createBuildEnvironment(),
  });
  try {
    return await build();
  } finally {
    if (processEnvironment === undefined) {
      Reflect.deleteProperty(process, "env");
    } else {
      Object.defineProperty(process, "env", processEnvironment);
    }
    release();
  }
}

async function instantiatePluginsFromSource(source: string): Promise<PluginOption[]> {
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
        resolveId(id) {
          return id === PLUGINS_VIRTUAL_ID ? RESOLVED_PLUGINS_VIRTUAL_ID : null;
        },
        load(id) {
          return id === RESOLVED_PLUGINS_VIRTUAL_ID ? moduleSource : null;
        },
      },
    ],
    root: PACKAGE_ROOT,
    server: { hmr: false, middlewareMode: true, ws: false },
  });
  try {
    const loaded = await server.ssrLoadModule(PLUGINS_VIRTUAL_ID);
    const plugins = (loaded as { default?: unknown }).default;
    if (!Array.isArray(plugins)) {
      throw new TypeError("@belgie/render: plugins module must default-export an array");
    }
    return plugins as PluginOption[];
  } finally {
    await server.close();
  }
}

export async function buildFromSource(source: string): Promise<string> {
  if (typeof source !== "string") {
    throw new TypeError("@belgie/render: source must be a string");
  }
  return withBuildLock(async () => {
    const context: RenderContext = {
      source,
      url: INLINE_SOURCE_URL,
      version: 1,
    };
    const plugins = await instantiatePluginsFromSource(source);
    return buildInlineWidget(context, plugins);
  });
}
