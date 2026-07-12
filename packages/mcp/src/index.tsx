import { StrictMode, useEffect, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";

export type BelgieProps = {
  children: ReactNode;
  title?: string;
};

let rootInstance: Root | null = null;

export function Belgie({ children, title }: BelgieProps) {
  useEffect(() => {
    if (title !== undefined) {
      document.title = title;
    }
  }, [title]);

  return <StrictMode>{children}</StrictMode>;
}

export function mountWidget(node: ReactNode): void {
  if (typeof document === "undefined" || typeof window === "undefined") {
    return;
  }

  if (!rootInstance) {
    rootInstance = createRoot(resolveRoot());
  }

  rootInstance.render(node);
}

function resolveRoot(): HTMLElement {
  const element = document.querySelector("#root");
  if (!(element instanceof HTMLElement)) {
    throw new Error("Belgie widget root #root was not found");
  }
  return element;
}
