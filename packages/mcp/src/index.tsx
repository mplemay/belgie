import {
  StrictMode,
  createContext,
  useContext,
  useEffect,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { createRoot, type Root } from "react-dom/client";
import type { App } from "@modelcontextprotocol/ext-apps";

export type BelgieProps = {
  app: App;
  children: ReactNode;
  fallback?: ReactNode;
  error?: ReactNode | ((error: Error) => ReactNode);
};

const BelgieAppContext = createContext<App | null>(null);

export function useApp(): App {
  const app = useContext(BelgieAppContext);
  if (app == null) {
    throw new Error("useApp must be used within a connected <Belgie>");
  }
  return app;
}

let rootInstance: Root | null = null;

export function Belgie({ app, children, fallback, error: errorUI }: BelgieProps) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    app
      .connect()
      .then(() => {
        if (!cancelled) {
          setConnected(true);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        // Strict Mode remount can hit connect twice; treat already-connected as success
        if (err instanceof Error && err.message.includes("already connected")) {
          setConnected(true);
          return;
        }
        setError(err instanceof Error ? err : new Error(String(err)));
      });
    return () => {
      cancelled = true;
    };
  }, [app]);

  if (error) {
    if (typeof errorUI === "function") return errorUI(error);
    if (errorUI !== undefined) return errorUI;
    return (
      <div>
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!connected) {
    return fallback ?? <div>Connecting...</div>;
  }

  return <BelgieAppContext.Provider value={app}>{children}</BelgieAppContext.Provider>;
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
