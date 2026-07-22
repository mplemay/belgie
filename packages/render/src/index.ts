import { isValidElement } from "react";
import type { ReactElement } from "react";
import type { PluginOption } from "vite";

import type { RenderContext } from "./build.js";

export interface RenderOptions {
  plugins?: PluginOption[];
  widget: ReactElement;
}

const CONTEXT_SYMBOL = Symbol.for("@belgie/render/context");
const BUILD_ENVIRONMENT_SEED: Record<string, string> = {
  APPVEYOR: "1",
  NODE_ENV: "production",
  TERM: "dumb",
};

function createBuildEnvironment(): Record<string, string> {
  return { ...BUILD_ENVIRONMENT_SEED };
}

function readContext(): RenderContext {
  const context = (globalThis as Record<PropertyKey, unknown>)[CONTEXT_SYMBOL];
  if (
    typeof context !== "object" ||
    context === null ||
    !("version" in context) ||
    context.version !== 1 ||
    !("source" in context) ||
    typeof context.source !== "string" ||
    !("url" in context) ||
    typeof context.url !== "string"
  ) {
    throw new Error("@belgie/render: missing Belgie inline script context");
  }
  return context as RenderContext;
}

function validatePlugins(plugins: PluginOption[] | undefined): PluginOption[] {
  if (plugins === undefined) {
    return [];
  }
  if (!Array.isArray(plugins)) {
    throw new TypeError("@belgie/render: plugins must be an array");
  }
  return plugins;
}

const renderLock: { gate: Promise<void> } = { gate: Promise.resolve() };

export async function render(options: RenderOptions): Promise<string> {
  if (typeof options !== "object" || options === null || !isValidElement(options.widget)) {
    throw new TypeError("@belgie/render: widget must be a React element");
  }
  const plugins = validatePlugins(options.plugins);
  const context = readContext();

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
    const { buildInlineWidget } = await import("./build.js");
    return await buildInlineWidget(context, plugins);
  } finally {
    if (processEnvironment === undefined) {
      Reflect.deleteProperty(process, "env");
    } else {
      Object.defineProperty(process, "env", processEnvironment);
    }
    release();
  }
}
