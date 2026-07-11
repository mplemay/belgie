import { createRoot } from "react-dom/client";
import type { ReactNode } from "react";

export type WidgetMetadata = {
  title?: string;
};

export type RenderOptions = {
  metadata?: WidgetMetadata;
  root?: HTMLElement | string | null;
  widget: ReactNode;
};

export type RenderResult = {
  metadata?: WidgetMetadata;
};

export function render({ metadata, root, widget }: RenderOptions): RenderResult {
  if (typeof document === "undefined" || typeof window === "undefined") {
    return { metadata };
  }

  if (metadata?.title) {
    document.title = metadata.title;
  }

  createRoot(resolveRoot(root)).render(widget);
  return { metadata };
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
