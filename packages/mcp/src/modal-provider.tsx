import { useEffect, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import { closeModal, getModalDisplay, hasAppsSdkModal, subscribeModalDisplay } from "./modal";

const MODAL_STYLES = `
.bg-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 9998;
}
.bg-modal-container {
  border-radius: 12px;
  position: fixed;
  inset: 0;
  margin: auto;
  width: fit-content;
  height: fit-content;
  background: white;
  z-index: 9999;
}
`;

export function ModalProvider({ children }: { children: ReactNode }) {
  const { mode } = useSyncExternalStore(subscribeModalDisplay, getModalDisplay, getModalDisplay);
  // ChatGPT owns modal chrome outside the iframe; only polyfill hosts get backdrop UI.
  const isOpen = !hasAppsSdkModal() && mode === "modal";

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeModal();
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
    };
  }, [isOpen]);

  if (!isOpen) {
    return children;
  }

  return (
    <>
      <style>{MODAL_STYLES}</style>
      <div
        role="presentation"
        className="bg-modal-backdrop"
        onClick={() => {
          closeModal();
        }}
      />
      <div className="bg-modal-container">{children}</div>
    </>
  );
}
