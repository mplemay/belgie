// @vitest-environment jsdom

import assert from "node:assert/strict";
import { describe, test } from "vitest";

import type {
  App,
  AppEventMap,
  McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";
import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";

import {
  useDisplayMode,
  useLayout,
  useLocale,
  useTheme,
  useUserAgent,
} from "../src/host-context";
import {
  WidgetContext,
  type WidgetContextValue,
} from "../src/widget-context";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type TestRenderer = {
  root: Root;
  unmount: () => void;
};

type HostContextHarness = {
  app: App;
  displayModeRequests: McpUiHostContext["displayMode"][];
  listenerCount: () => number;
  update: (context: McpUiHostContext) => void;
};

type HostContextSnapshot = {
  displayMode: ReturnType<typeof useDisplayMode>[0];
  setDisplayMode: ReturnType<typeof useDisplayMode>[1];
  layout: ReturnType<typeof useLayout>;
  locale: ReturnType<typeof useLocale>;
  theme: ReturnType<typeof useTheme>;
  userAgent: ReturnType<typeof useUserAgent>;
};

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
    unmount() {
      root.unmount();
      container.remove();
    },
  };
}

function createHostContextHarness(
  initialContext: McpUiHostContext,
): HostContextHarness {
  let context = initialContext;
  const listeners = new Set<
    (params: AppEventMap["hostcontextchanged"]) => void
  >();
  const displayModeRequests: McpUiHostContext["displayMode"][] = [];
  const app = {
    addEventListener(name, handler) {
      assert.equal(name, "hostcontextchanged");
      listeners.add(handler);
    },
    getHostContext() {
      return context;
    },
    removeEventListener(name, handler) {
      assert.equal(name, "hostcontextchanged");
      listeners.delete(handler);
    },
    async requestDisplayMode({ mode }) {
      displayModeRequests.push(mode);
      return { mode: mode === "pip" ? "fullscreen" : mode };
    },
  } as App;

  return {
    app,
    displayModeRequests,
    listenerCount: () => listeners.size,
    update(nextContext) {
      context = { ...context, ...nextContext };
      for (const listener of [...listeners]) {
        listener(nextContext);
      }
    },
  };
}

function HostContextProbe({
  rendered,
}: {
  rendered: (snapshot: HostContextSnapshot) => void;
}) {
  const [displayMode, setDisplayMode] = useDisplayMode();
  const layout = useLayout();
  const locale = useLocale();
  const theme = useTheme();
  const userAgent = useUserAgent();
  rendered({
    displayMode,
    setDisplayMode,
    layout,
    locale,
    theme,
    userAgent,
  });
  return createElement("span", null, "host context");
}

function renderHostContextProbe(
  harness: HostContextHarness,
  rendered: (snapshot: HostContextSnapshot) => void,
): TestRenderer {
  return create(
    createElement(
      WidgetContext.Provider,
      { value: { app: harness.app, tool } },
      createElement(HostContextProbe, { rendered }),
    ),
  );
}

describe("host context hooks", () => {
  test("returns host values and reacts to relevant context changes", async () => {
    const harness = createHostContextHarness({
      displayMode: "fullscreen",
      theme: "dark",
      locale: "fr_FR",
      containerDimensions: { maxHeight: 500, width: 400 },
      safeAreaInsets: { top: 44, right: 0, bottom: 34, left: 0 },
      platform: "web",
      deviceCapabilities: { hover: true, touch: false },
    });
    let snapshot: HostContextSnapshot | undefined;
    let renderer: TestRenderer | undefined;
    try {
      await act(async () => {
        renderer = renderHostContextProbe(harness, (nextSnapshot) => {
          snapshot = nextSnapshot;
        });
      });

      assert(snapshot);
      assert.equal(snapshot.displayMode, "fullscreen");
      assert.deepEqual(snapshot.layout, {
        maxHeight: 500,
        safeArea: {
          insets: { top: 44, right: 0, bottom: 34, left: 0 },
        },
      });
      assert.equal(snapshot.locale, "fr-FR");
      assert.equal(snapshot.theme, "dark");
      assert.deepEqual(snapshot.userAgent, {
        device: { type: "desktop" },
        capabilities: { hover: true, touch: false },
      });
      const initialSafeArea = snapshot.layout.safeArea;
      const initialUserAgent = snapshot.userAgent;

      await act(async () => {
        harness.update({
          displayMode: "inline",
          theme: "light",
          locale: "zh_Hans_CN",
          containerDimensions: { maxHeight: 800, width: 400 },
          platform: "mobile",
          deviceCapabilities: { hover: false, touch: true },
        });
      });

      assert(snapshot);
      assert.equal(snapshot.displayMode, "inline");
      assert.equal(snapshot.layout.maxHeight, 800);
      assert.equal(snapshot.layout.safeArea, initialSafeArea);
      assert.equal(snapshot.locale, "zh-Hans-CN");
      assert.equal(snapshot.theme, "light");
      assert.notEqual(snapshot.userAgent, initialUserAgent);
      assert.deepEqual(snapshot.userAgent, {
        device: { type: "mobile" },
        capabilities: { hover: false, touch: true },
      });

      await act(async () => {
        harness.update({
          safeAreaInsets: { top: 20, right: 10, bottom: 5, left: 10 },
          platform: "desktop",
        });
      });

      assert(snapshot);
      assert.notEqual(snapshot.layout.safeArea, initialSafeArea);
      assert.deepEqual(snapshot.layout.safeArea.insets, {
        top: 20,
        right: 10,
        bottom: 5,
        left: 10,
      });
      assert.equal(snapshot.userAgent.device.type, "desktop");

      const result = await snapshot.setDisplayMode("pip");
      assert.deepEqual(harness.displayModeRequests, ["pip"]);
      assert.equal(result.mode, "fullscreen");
      assert.equal(harness.listenerCount(), 7);
    } finally {
      if (renderer !== undefined) {
        await act(async () => renderer.unmount());
      }
    }
    assert.equal(harness.listenerCount(), 0);
  });

  test("returns stable Skybridge-compatible defaults", async () => {
    const harness = createHostContextHarness({
      containerDimensions: { height: 300, width: 400 },
    });
    let snapshot: HostContextSnapshot | undefined;
    let renderer: TestRenderer | undefined;
    try {
      await act(async () => {
        renderer = renderHostContextProbe(harness, (nextSnapshot) => {
          snapshot = nextSnapshot;
        });
      });

      assert(snapshot);
      assert.equal(snapshot.displayMode, "inline");
      assert.deepEqual(snapshot.layout, {
        maxHeight: undefined,
        safeArea: {
          insets: { top: 0, right: 0, bottom: 0, left: 0 },
        },
      });
      assert.equal(snapshot.locale, "en-US");
      assert.equal(snapshot.theme, "light");
      assert.deepEqual(snapshot.userAgent, {
        device: { type: "unknown" },
        capabilities: { hover: true, touch: true },
      });
      const initialSafeArea = snapshot.layout.safeArea;
      const initialUserAgent = snapshot.userAgent;

      await act(async () => {
        harness.update({ timeZone: "America/Chicago" });
      });

      assert(snapshot);
      assert.equal(snapshot.layout.safeArea, initialSafeArea);
      assert.equal(snapshot.userAgent, initialUserAgent);
    } finally {
      if (renderer !== undefined) {
        await act(async () => renderer.unmount());
      }
    }
  });

  test("falls back for an invalid locale", async () => {
    const harness = createHostContextHarness({ locale: "not-a-locale-!!" });
    let snapshot: HostContextSnapshot | undefined;
    let renderer: TestRenderer | undefined;
    try {
      await act(async () => {
        renderer = renderHostContextProbe(harness, (nextSnapshot) => {
          snapshot = nextSnapshot;
        });
      });

      assert.equal(snapshot?.locale, "en-US");
    } finally {
      if (renderer !== undefined) {
        await act(async () => renderer.unmount());
      }
    }
  });

  test("requires a connected Widget context", () => {
    const hooks = [
      useDisplayMode,
      useLayout,
      useLocale,
      useTheme,
      useUserAgent,
    ];

    for (const hook of hooks) {
      function Probe() {
        hook();
        return null;
      }

      assert.throws(
        () => renderToString(createElement(Probe)),
        new RegExp(`${hook.name} must be used within a connected <Widget>`, "u"),
      );
    }
  });
});
