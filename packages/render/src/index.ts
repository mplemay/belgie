import { isValidElement, type ReactElement } from "react";
import type { PluginOption } from "vite";

import type { RenderContext } from "./build.js";

export type RenderOptions = {
  plugins?: PluginOption[];
  widget: ReactElement;
};

const CONTEXT_SYMBOL = Symbol.for("@belgie/render/context");
const BUILD_ENVIRONMENT = Object.freeze({ APPVEYOR: "1", NODE_ENV: "production", TERM: "dumb" });

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

export async function render(options: RenderOptions): Promise<string> {
  if (typeof options !== "object" || options === null || !isValidElement(options.widget)) {
    throw new TypeError("@belgie/render: widget must be a React element");
  }
  const processEnvironment = Object.getOwnPropertyDescriptor(process, "env");
  Object.defineProperty(process, "env", {
    configurable: true,
    value: BUILD_ENVIRONMENT,
  });
  try {
    const { buildInlineWidget } = await import("./build.js");
    return await buildInlineWidget(readContext(), validatePlugins(options.plugins));
  } finally {
    if (processEnvironment === undefined) {
      Reflect.deleteProperty(process, "env");
    } else {
      Object.defineProperty(process, "env", processEnvironment);
    }
  }
}
