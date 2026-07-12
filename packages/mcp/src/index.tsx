import { StrictMode, useEffect, type ComponentType, type ReactNode } from "react";
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
