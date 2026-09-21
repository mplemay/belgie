import assert from "node:assert/strict";

import { isWidget, useIsWidget } from "../src/is-widget";

interface WindowStub {
  location: { origin: string };
  openai?: { requestModal?: () => void } | Record<string, never>;
}

function withWindow(window: WindowStub | undefined, run: () => void): void {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  if (window === undefined) {
    Reflect.deleteProperty(globalThis, "window");
  } else {
    Object.defineProperty(globalThis, "window", { configurable: true, value: window });
  }
  try {
    run();
  } finally {
    if (previous === undefined) {
      Reflect.deleteProperty(globalThis, "window");
    } else {
      Object.defineProperty(globalThis, "window", previous);
    }
  }
}

test("isWidget is false without a window", () => {
  withWindow(undefined, () => {
    assert.equal(isWidget(), false);
    assert.equal(useIsWidget(), false);
  });
});

test("isWidget is false on a normal web origin", () => {
  withWindow({ location: { origin: "http://localhost:3000" } }, () => {
    assert.equal(isWidget(), false);
    assert.equal(useIsWidget(), false);
  });
});

test("isWidget is true in an opaque MCP Apps sandbox", () => {
  withWindow({ location: { origin: "null" } }, () => {
    assert.equal(isWidget(), true);
    assert.equal(useIsWidget(), true);
  });
});

test("isWidget is true when the ChatGPT Apps SDK overlay is present", () => {
  withWindow(
    {
      location: { origin: "https://chatgpt.com" },
      openai: { requestModal: () => {} },
    },
    () => {
      assert.equal(isWidget(), true);
      assert.equal(useIsWidget(), true);
    },
  );
});

test("isWidget ignores a window.openai object without requestModal", () => {
  withWindow(
    {
      location: { origin: "https://example.com" },
      openai: {},
    },
    () => {
      assert.equal(isWidget(), false);
    },
  );
});
