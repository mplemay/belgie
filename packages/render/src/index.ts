import { isValidElement } from "react";
import type { ReactElement } from "react";
import type { PluginOption } from "vite";

import type { RenderContext } from "./build.js";

export interface RenderOptions {
  plugins?: PluginOption[];
  widget: ReactElement;
}

export const RENDER_REQUEST_KEY = "__belgie_render_request__" as const;

export interface RenderRequest {
  readonly [RENDER_REQUEST_KEY]: 1;
}

export const RENDER_REQUEST: RenderRequest = Object.freeze({ [RENDER_REQUEST_KEY]: 1 });

const CONTEXT_SYMBOL = Symbol.for("@belgie/render/context");

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

function assertPlugins(plugins: PluginOption[] | undefined): void {
  if (plugins !== undefined && !Array.isArray(plugins)) {
    throw new TypeError("@belgie/render: plugins must be an array");
  }
}

export function isRenderRequest(value: unknown): value is RenderRequest {
  return (
    typeof value === "object" &&
    value !== null &&
    RENDER_REQUEST_KEY in value &&
    (value as RenderRequest)[RENDER_REQUEST_KEY] === 1
  );
}

export async function render(options: RenderOptions): Promise<string> {
  if (typeof options !== "object" || options === null || !isValidElement(options.widget)) {
    throw new TypeError("@belgie/render: widget must be a React element");
  }
  assertPlugins(options.plugins);
  readContext();
  // Host (BelgieRuntimeSession) replaces this sentinel with HTML from buildFromSource.
  return RENDER_REQUEST as unknown as string;
}
