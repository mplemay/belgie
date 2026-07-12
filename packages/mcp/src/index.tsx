import { StrictMode, type ComponentType, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  useApp,
  type AppState,
  type UseAppOptions,
} from "@modelcontextprotocol/ext-apps/react";

export type { App } from "@modelcontextprotocol/ext-apps";
export { useApp, type AppState, type UseAppOptions } from "@modelcontextprotocol/ext-apps/react";

export type BelgieProps = UseAppOptions & { children: ReactNode };

let rootInstance: Root | null = null;

export function Belgie({ children, ...options }: BelgieProps) {
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
