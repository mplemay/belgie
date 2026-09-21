import { hasAppsSdkModal } from "./modal";

export function isWidget(): boolean {
  const view = globalThis.window;
  if (view === undefined) {
    return false;
  }
  // MCP Apps / Skybridge guest iframes use an opaque sandbox origin.
  if (view.location.origin === "null") {
    return true;
  }
  return hasAppsSdkModal();
}

export function useIsWidget(): boolean {
  return isWidget();
}
