// @vitest-environment jsdom

import assert from "node:assert/strict";

import type { App } from "@modelcontextprotocol/ext-apps";
import { act, createElement } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { renderToString } from "react-dom/server";

import { closeModal as closeModalHelper, requestModal } from "../src/app";
import { closeModal, getModalDisplay, openModal, resetModalState, subscribeModalDisplay } from "../src/modal";
import { ModalProvider } from "../src/modal-provider";
import { useModal } from "../src/use-modal";
import { WidgetContext, activateWidget, deactivateWidget } from "../src/widget-context";
import type { WidgetContextValue } from "../src/widget-context";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

interface TestRenderer {
  root: Root;
  container: HTMLDivElement;
  unmount: () => void;
}

interface ModalSnapshot {
  isOpen: boolean;
  params: Record<string, unknown> | undefined;
  open: ReturnType<typeof useModal>["open"];
}

const tool: WidgetContextValue["tool"] = {
  input: undefined,
  inputReceived: false,
  rawResult: undefined,
  cancellationReason: undefined,
  status: "pending",
  version: 0,
};

function create(node: ReactNode): TestRenderer {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  root.render(node);
  return {
    root,
    container,
    unmount() {
      root.unmount();
      container.remove();
    },
  };
}

function ModalProbe({ rendered }: { rendered: (snapshot: ModalSnapshot) => void }) {
  const modal = useModal();
  rendered(modal);
  return createElement("span", null, modal.isOpen ? "open" : "closed");
}

function renderModalProbe(app: App, rendered: (snapshot: ModalSnapshot) => void): TestRenderer {
  return create(
    createElement(
      WidgetContext.Provider,
      { value: { app, tool } },
      createElement(ModalProvider, null, createElement(ModalProbe, { rendered })),
    ),
  );
}

describe("modal hook", () => {
  afterEach(() => {
    resetModalState();
    Reflect.deleteProperty(globalThis, "openai");
  });

  it("requires a connected Widget context", () => {
    assert.equal(
      renderToString(
        createElement(() => {
          try {
            useModal();
            return createElement("span", null, "ok");
          } catch (error) {
            return createElement("span", null, error instanceof Error ? error.message : String(error));
          }
        }),
      ),
      "<span>useModal must be used within a connected &lt;Widget&gt;</span>",
    );
  });

  it("opens and closes through the polyfill display store", async () => {
    const app = {} as App;
    let snapshot: ModalSnapshot | undefined;
    let renderer: TestRenderer | undefined;
    try {
      activateWidget(app);
      await act(async () => {
        renderer = renderModalProbe(app, (next) => {
          snapshot = next;
        });
      });

      assert.ok(snapshot);
      assert.equal(snapshot.isOpen, false);
      assert.equal(snapshot.params, undefined);

      await act(async () => {
        snapshot!.open({ params: { productId: 42 } });
      });

      assert.ok(snapshot);
      assert.equal(snapshot.isOpen, true);
      assert.deepEqual(snapshot.params, { productId: 42 });
      assert.equal(renderer!.container.querySelector(".bg-modal-backdrop") !== null, true);
      assert.equal(renderer!.container.querySelector(".bg-modal-container") !== null, true);

      await act(async () => {
        closeModal();
      });

      assert.ok(snapshot);
      assert.equal(snapshot.isOpen, false);
      assert.equal(snapshot.params, undefined);
      assert.equal(renderer!.container.querySelector(".bg-modal-backdrop"), null);
    } finally {
      deactivateWidget(app);
      renderer?.unmount();
    }
  });

  it("closes the polyfill modal on Escape and backdrop click", async () => {
    const app = {} as App;
    let snapshot: ModalSnapshot | undefined;
    let renderer: TestRenderer | undefined;
    try {
      activateWidget(app);
      await act(async () => {
        renderer = renderModalProbe(app, (next) => {
          snapshot = next;
        });
      });

      await act(async () => {
        openModal({ params: { id: "escape" } });
      });
      assert.equal(snapshot?.isOpen, true);

      await act(async () => {
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
      });
      assert.equal(snapshot?.isOpen, true);

      await act(async () => {
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      });
      assert.equal(snapshot?.isOpen, false);

      await act(async () => {
        openModal({});
      });
      assert.equal(snapshot?.isOpen, true);

      const backdrop = renderer!.container.querySelector(".bg-modal-backdrop");
      assert.ok(backdrop instanceof HTMLElement);
      await act(async () => {
        backdrop.click();
      });
      assert.equal(snapshot?.isOpen, false);
    } finally {
      deactivateWidget(app);
      renderer?.unmount();
    }
  });

  it("exposes requestModal and closeModal helpers through the active Widget", async () => {
    const app = {} as App;
    try {
      activateWidget(app);
      requestModal({ params: { fromHelper: true } });
      assert.equal(getModalDisplay().mode, "modal");
      assert.deepEqual(getModalDisplay().params, { fromHelper: true });

      closeModalHelper();
      assert.equal(getModalDisplay().mode, "inline");
    } finally {
      deactivateWidget(app);
      resetModalState();
    }
  });

  it("ignores closeModal on Apps SDK hosts", () => {
    const requestModalMock = vi.fn();
    Object.defineProperty(globalThis, "openai", {
      configurable: true,
      value: {
        requestModal: requestModalMock,
        view: { mode: "modal", params: { keep: true } },
      },
    });

    assert.equal(getModalDisplay().mode, "modal");
    assert.equal(getModalDisplay().params, getModalDisplay().params);
    closeModal();
    assert.equal(getModalDisplay().mode, "modal");
    assert.deepEqual(getModalDisplay().params, { keep: true });
  });

  it("ignores openai globals without a requestModal function", () => {
    Object.defineProperty(globalThis, "openai", {
      configurable: true,
      value: { view: { mode: "modal" } },
    });
    openModal({ params: { polyfill: true } });
    assert.equal(getModalDisplay().mode, "modal");
    assert.deepEqual(getModalDisplay().params, { polyfill: true });
  });

  it("ignores Apps SDK globals events that omit view", () => {
    const requestModalMock = vi.fn();
    let notifications = 0;
    Object.defineProperty(globalThis, "openai", {
      configurable: true,
      value: {
        requestModal: requestModalMock,
        view: { mode: "inline" },
      },
    });
    const unsubscribe = subscribeModalDisplay(() => {
      notifications += 1;
    });
    globalThis.dispatchEvent(
      new CustomEvent("openai:set_globals", {
        detail: { globals: { theme: "dark" } },
      }),
    );
    assert.equal(notifications, 0);
    unsubscribe();
  });

  it("delegates open to window.openai.requestModal on Apps SDK hosts", async () => {
    const requestModalFn = vi.fn();
    Object.defineProperty(globalThis, "openai", {
      configurable: true,
      value: {
        requestModal: requestModalFn,
        view: { mode: "inline" },
      },
    });

    const app = {} as App;
    let snapshot: ModalSnapshot | undefined;
    let renderer: TestRenderer | undefined;
    try {
      activateWidget(app);
      await act(async () => {
        renderer = renderModalProbe(app, (next) => {
          snapshot = next;
        });
      });

      const options = {
        title: "Confirm",
        params: { foo: "bar" },
        template: "ui://view/modal.html",
      };
      await act(async () => {
        snapshot!.open(options);
      });

      assert.equal(requestModalFn.mock.calls.length, 1);
      assert.deepEqual(requestModalFn.mock.calls[0]?.[0], options);
      assert.equal(snapshot?.isOpen, false);
      assert.equal(renderer!.container.querySelector(".bg-modal-backdrop"), null);

      Object.defineProperty(globalThis, "openai", {
        configurable: true,
        value: {
          requestModal: requestModalFn,
          view: { mode: "modal", params: { foo: "bar" } },
        },
      });
      await act(async () => {
        globalThis.dispatchEvent(
          new CustomEvent("openai:set_globals", {
            detail: { globals: { view: { mode: "modal", params: { foo: "bar" } } } },
          }),
        );
      });

      assert.equal(snapshot?.isOpen, true);
      assert.deepEqual(snapshot?.params, { foo: "bar" });
      assert.equal(renderer!.container.querySelector(".bg-modal-backdrop"), null);
    } finally {
      deactivateWidget(app);
      renderer?.unmount();
    }
  });
});
