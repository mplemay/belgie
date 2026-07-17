import { createContext, useContext } from "react";

import type { App } from "@modelcontextprotocol/ext-apps";
import type { RawToolResult } from "./tool-error";

export type WidgetToolLifecycle = {
  input: Record<string, unknown> | undefined;
  inputReceived: boolean;
  rawResult: RawToolResult | undefined;
  cancellationReason: string | undefined;
  status: "pending" | "result" | "cancelled";
  version: number;
};

export type WidgetContextValue = {
  app: App;
  tool: WidgetToolLifecycle;
};

export const WidgetContext = createContext<WidgetContextValue | null>(null);

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

export function useWidgetContext(): WidgetContextValue | null {
  return useContext(WidgetContext);
}

export function useConnectedWidgetContext(name: string): WidgetContextValue {
  const context = useWidgetContext();
  if (context == null) {
    throw new Error(`${name} must be used within a connected <Widget>`);
  }
  return context;
}

export function useWidget(): App {
  return useConnectedWidgetContext("useWidget").app;
}
