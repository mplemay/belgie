import { createContext, useContext } from "react";

import type { App } from "@modelcontextprotocol/ext-apps";

export const WidgetContext = createContext<App | null>(null);

export function useWidget(): App {
  const app = useContext(WidgetContext);
  if (app == null) {
    throw new Error("useWidget must be used within a connected <Widget>");
  }
  return app;
}
