import { createContext, useContext } from "react";

import type { App } from "@modelcontextprotocol/ext-apps";

export const WidgetContext = createContext<App | null>(null);

let activeWidget: App | null = null;

export function activateWidget(app: App): void {
  if (activeWidget !== null && activeWidget !== app) {
    throw new Error("Only one connected <Widget> can be active at a time");
  }
  activeWidget = app;
}

export function deactivateWidget(app: App): void {
  if (activeWidget === app) {
    activeWidget = null;
  }
}

export function getActiveWidget(): App {
  if (activeWidget === null) {
    throw new Error("Tool calls require an active connected <Widget>");
  }
  return activeWidget;
}

export function useWidgetContext(): App | null {
  return useContext(WidgetContext);
}

export function useWidget(): App {
  const app = useWidgetContext();
  if (app == null) {
    throw new Error("useWidget must be used within a connected <Widget>");
  }
  return app;
}
