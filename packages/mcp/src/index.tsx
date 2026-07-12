import { StrictMode, type ComponentType, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  useApp,
  type AppState,
  type UseAppOptions,
} from "@modelcontextprotocol/ext-apps/react";

export type { App } from "@modelcontextprotocol/ext-apps";
export { useApp, type AppState, type UseAppOptions } from "@modelcontextprotocol/ext-apps/react";

export type BelgieProps = UseAppOptions & {
  children: ReactNode;
  fallback?: ReactNode;
  error?: ReactNode | ((error: Error) => ReactNode);
};

let rootInstance: Root | null = null;

export function Belgie({
  children,
  fallback,
  error: errorUI,
  ...options
}: BelgieProps) {
  const { app, error }: AppState = useApp(options);

  if (error) {
    if (typeof errorUI === "function") return errorUI(error);
    if (errorUI !== undefined) return errorUI;
    return (
      <div>
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!app) {
    return fallback ?? <div>Connecting...</div>;
  }

  return children;
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
