import { createRoot } from "react-dom/client";
import type { ReactNode } from "react";
import type { PluginOption } from "vite";

import { WIDGET_RENDER_MANIFEST, type WidgetRenderManifest } from "./manifest.ts";

export type WidgetMetadata = {
  title?: string;
};

export type RenderOptions = {
  metadata?: WidgetMetadata;
  plugins?: PluginOption[];
  root?: HTMLElement | string | null;
  widget: ReactNode;
};

export type RenderResult = {
  manifest: WidgetRenderManifest;
  metadata?: WidgetMetadata;
  plugins?: PluginOption[];
};

export function render({ metadata, plugins, root, widget }: RenderOptions): RenderResult {
  if (!isBrowserEnvironment()) {
    return { manifest: WIDGET_RENDER_MANIFEST, metadata, plugins };
  }

  if (metadata?.title) {
    document.title = metadata.title;
  }

  createRoot(resolveRoot(root)).render(widget);
  return { manifest: WIDGET_RENDER_MANIFEST, metadata, plugins };
}

function isBrowserEnvironment(): boolean {
  return typeof document !== "undefined" && typeof window !== "undefined";
}

function resolveRoot(root: HTMLElement | string | null | undefined): HTMLElement {
  if (root instanceof HTMLElement) {
    return root;
  }

  const selector = root ?? "#root";
  const element = document.querySelector(selector);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Belgie widget root ${selector} was not found`);
  }
  return element;
}
