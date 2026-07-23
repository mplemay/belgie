export interface ModalOptions {
  title?: string;
  params?: Record<string, unknown>;
  template?: string;
  anchor?: { top?: number; left?: number; width?: number; height?: number };
}

export interface ModalDisplay {
  mode: "inline" | "modal";
  params?: Record<string, unknown>;
}

interface AppsSdkView {
  mode: string;
  params?: Record<string, unknown>;
}

interface AppsSdkOpenAI {
  requestModal: (options: ModalOptions) => void | Promise<void>;
  view?: AppsSdkView;
}

const SET_GLOBALS_EVENT_TYPE = "openai:set_globals";
const DEFAULT_DISPLAY: ModalDisplay = { mode: "inline" };

const modalState: {
  polyfillDisplay: ModalDisplay;
  appsSdkDisplay: ModalDisplay;
} = {
  polyfillDisplay: DEFAULT_DISPLAY,
  appsSdkDisplay: DEFAULT_DISPLAY,
};
const polyfillListeners = new Set<() => void>();

function getOpenAI(): AppsSdkOpenAI | undefined {
  const openai = (globalThis as { window?: Window & { openai?: AppsSdkOpenAI } }).window?.openai;
  if (openai === undefined || typeof openai.requestModal !== "function") {
    return undefined;
  }
  return openai;
}

export function hasAppsSdkModal(): boolean {
  return getOpenAI() !== undefined;
}

function notifyPolyfillListeners(): void {
  for (const listener of [...polyfillListeners]) {
    listener();
  }
}

export function openModal(options: ModalOptions): void {
  const openai = getOpenAI();
  if (openai !== undefined) {
    void openai.requestModal(options);
    return;
  }
  modalState.polyfillDisplay =
    options.params === undefined ? { mode: "modal" } : { mode: "modal", params: options.params };
  notifyPolyfillListeners();
}

export function closeModal(): void {
  if (hasAppsSdkModal()) {
    return;
  }
  modalState.polyfillDisplay = DEFAULT_DISPLAY;
  notifyPolyfillListeners();
}

function readAppsSdkDisplay(openai: AppsSdkOpenAI): ModalDisplay {
  const view = openai.view;
  if (view?.mode !== "modal") {
    return DEFAULT_DISPLAY;
  }
  if (modalState.appsSdkDisplay.mode === "modal" && modalState.appsSdkDisplay.params === view.params) {
    return modalState.appsSdkDisplay;
  }
  modalState.appsSdkDisplay = view.params === undefined ? { mode: "modal" } : { mode: "modal", params: view.params };
  return modalState.appsSdkDisplay;
}

export function getModalDisplay(): ModalDisplay {
  const openai = getOpenAI();
  if (openai !== undefined) {
    return readAppsSdkDisplay(openai);
  }
  return modalState.polyfillDisplay;
}

export function subscribeModalDisplay(onChange: () => void): () => void {
  if (hasAppsSdkModal()) {
    const handleSetGlobals = (event: Event) => {
      const detail = (event as CustomEvent<{ globals?: { view?: AppsSdkView } }>).detail;
      if (detail?.globals !== undefined && "view" in detail.globals) {
        onChange();
      }
    };
    globalThis.addEventListener(SET_GLOBALS_EVENT_TYPE, handleSetGlobals);
    return () => {
      globalThis.removeEventListener(SET_GLOBALS_EVENT_TYPE, handleSetGlobals);
    };
  }

  polyfillListeners.add(onChange);
  return () => {
    polyfillListeners.delete(onChange);
  };
}

export function resetModalState(): void {
  modalState.polyfillDisplay = DEFAULT_DISPLAY;
  modalState.appsSdkDisplay = DEFAULT_DISPLAY;
  polyfillListeners.clear();
}
