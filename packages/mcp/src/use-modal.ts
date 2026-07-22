import { useCallback, useSyncExternalStore } from "react";

import { getModalDisplay, openModal, subscribeModalDisplay } from "./modal";
import type { ModalOptions } from "./modal";
import { useConnectedWidgetContext } from "./widget-context";

export function useModal() {
  useConnectedWidgetContext("useModal");
  const display = useSyncExternalStore(subscribeModalDisplay, getModalDisplay, getModalDisplay);
  const open = useCallback((options: ModalOptions) => {
    openModal(options);
  }, []);

  return {
    isOpen: display.mode === "modal",
    params: display.params,
    open,
  } as const;
}
