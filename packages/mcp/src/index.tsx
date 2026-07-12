import {
  StrictMode,
  createContext,
  useContext,
  type ComponentType,
  type ReactNode,
} from "react";
import { createRoot, type Root } from "react-dom/client";
import type { App } from "@modelcontextprotocol/ext-apps";
import {
  useApp,
  type AppState,
  type UseAppOptions,
} from "@modelcontextprotocol/ext-apps/react";

export type { App } from "@modelcontextprotocol/ext-apps";
export { useApp, type AppState, type UseAppOptions } from "@modelcontextprotocol/ext-apps/react";

export type BelgieProps =
  | { app: App; children: ReactNode }
  | (UseAppOptions & { children: ReactNode; app?: never });

const BelgieAppContext = createContext<App | null>(null);

export function useBelgieApp(): App {
  const app = useContext(BelgieAppContext);
  if (app == null) {
    throw new Error("useBelgieApp must be used within a connected <Belgie>");
  }
  return app;
}

function BelgieProvider({ app, children }: { app: App; children: ReactNode }) {
  return <BelgieAppContext.Provider value={app}>{children}</BelgieAppContext.Provider>;
}

function BelgieFromOptions({
  children,
  ...options
}: UseAppOptions & { children: ReactNode }) {
  const { app, error }: AppState = useApp(options);

  if (error) {
    return (
      <div>
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!app) {
    return <div>Connecting...</div>;
  }

  return <BelgieProvider app={app}>{children}</BelgieProvider>;
}

let rootInstance: Root | null = null;

export function Belgie(props: BelgieProps) {
  if (props.app != null) {
    return <BelgieProvider app={props.app}>{props.children}</BelgieProvider>;
  }
  return <BelgieFromOptions {...props} />;
}

export function mountWidget(Widget: ComponentType): void {
  if (!rootInstance) {
    const element = document.querySelector("#root");
    if (!(element instanceof HTMLElement)) {
      throw new Error("Belgie widget root #root was not found");
    }
    rootInstance = createRoot(element);
  }

  rootInstance.render(
    <StrictMode>
      <Widget />
    </StrictMode>,
  );
}
