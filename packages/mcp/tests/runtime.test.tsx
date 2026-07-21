// @vitest-environment jsdom

import assert from "node:assert/strict";
import { describe, test } from "vitest";

import { App } from "@modelcontextprotocol/ext-apps";
import { StrictMode, act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ZodError } from "zod";

import pythonMcpV2Tools from "./fixtures/python-mcp-v2-tools.json";

import {
  McpToolCancelledError,
  McpToolError,
  Widget,
  downloadFile,
  openLink,
  requestDisplayMode,
  requestTeardown,
  sendLog,
  sendMessage,
  mountWidget,
  updateModelContext,
  useToolResult,
  useWidget,
} from "../src/index.tsx";
import {
  createGeneratedRawTool,
  createGeneratedTool,
} from "../src/internal.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type TestRenderer = {
  root: Root;
  container: HTMLDivElement;
  unmount: () => void;
  toJSON: () => string;
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
    toJSON: () => container.textContent ?? "",
  };
}

const outputSchema = {
  type: "object",
  properties: { value: { type: "string" } },
  required: ["value"],
  additionalProperties: false,
};
const getValue = createGeneratedTool("get-value", outputSchema);

let contentBlocksToolPromise;
async function contentBlocksTool() {
  contentBlocksToolPromise ??= (async () => {
    const contentBlocksSchema = pythonMcpV2Tools.find(
      (tool) => tool.name === "content-blocks",
    )?.outputSchema;
    assert(contentBlocksSchema);
    return createGeneratedTool("content-blocks", contentBlocksSchema);
  })();
  return contentBlocksToolPromise;
}

function stubApp({
  connect = async () => {},
  close = async () => {},
  call,
  methods = {},
}) {
  const listeners = new WeakMap();
  const originals = {
    addEventListener: App.prototype.addEventListener,
    connect: App.prototype.connect,
    close: App.prototype.close,
    callServerTool: App.prototype.callServerTool,
    removeEventListener: App.prototype.removeEventListener,
    methods: Object.fromEntries(
      Object.keys(methods).map((name) => [name, App.prototype[name]]),
    ),
  };
  App.prototype.connect = connect;
  App.prototype.close = close;
  App.prototype.addEventListener = function addEventListener(name, handler) {
    let appListeners = listeners.get(this);
    if (appListeners === undefined) {
      appListeners = new Map();
      listeners.set(this, appListeners);
    }
    const eventListeners = appListeners.get(name) ?? [];
    eventListeners.push(handler);
    appListeners.set(name, eventListeners);
  };
  App.prototype.removeEventListener = function removeEventListener(name, handler) {
    const eventListeners = listeners.get(this)?.get(name);
    if (eventListeners === undefined) return;
    const index = eventListeners.indexOf(handler);
    if (index !== -1) eventListeners.splice(index, 1);
  };
  if (call !== undefined) {
    App.prototype.callServerTool = call;
  }
  Object.assign(App.prototype, methods);
  const restore = () => {
    App.prototype.addEventListener = originals.addEventListener;
    App.prototype.connect = originals.connect;
    App.prototype.close = originals.close;
    App.prototype.callServerTool = originals.callServerTool;
    App.prototype.removeEventListener = originals.removeEventListener;
    Object.assign(App.prototype, originals.methods);
  };
  restore.emit = (app, name, params) => {
    for (const handler of [...(listeners.get(app)?.get(name) ?? [])]) {
      handler(params);
    }
  };
  return restore;
}

function ResultProbe({ source, rendered }) {
  rendered(useToolResult(source));
  return createElement("span", null, "result");
}

test("parses successful structured output through an explicit app", async () => {
  const structuredContent = { value: "parsed" };
  const requests = [];
  const app = {
    async callServerTool(request) {
      requests.push(request);
      return { content: [], structuredContent };
    },
  };

  const response = await getValue({ source: "explicit" }, app);
  assert.deepEqual(response, {
    result: { value: "parsed" },
    error: undefined,
  });
  assert.notEqual(response.result, structuredContent);
  assert.deepEqual(requests, [
    { name: "get-value", arguments: { source: "explicit" } },
  ]);
});

test("omits arguments for an omitted optional input", async () => {
  const getEmpty = createGeneratedTool("get-empty", outputSchema);
  let request;
  const app = {
    async callServerTool(nextRequest) {
      request = nextRequest;
      return { content: [], structuredContent: { value: "empty" } };
    },
  };

  assert.deepEqual(await getEmpty(undefined, app), {
    result: { value: "empty" },
    error: undefined,
  });
  assert.deepEqual(request, { name: "get-empty" });
});

test("parses nested MCP content blocks from the Python SDK schema", async () => {
  const getContentBlocks = await contentBlocksTool();
  const structuredContent = {
    result: [
      {
        type: "text",
        text: "visible",
        annotations: {
          audience: ["user"],
          priority: 0.5,
          lastModified: "2026-07-16T00:00:00Z",
        },
        _meta: { textId: "example" },
      },
      { type: "image", data: "aW1hZ2U=", mimeType: "image/png" },
      { type: "audio", data: "YXVkaW8=", mimeType: "audio/wav" },
      {
        type: "resource_link",
        uri: "https://example.com/resource",
        name: "Resource",
        icons: [
          {
            src: "https://example.com/icon.png",
            sizes: ["32x32"],
            theme: "dark",
          },
        ],
      },
      {
        type: "resource",
        resource: {
          uri: "https://example.com/text",
          text: "resource text",
          mimeType: "text/plain",
          _meta: { resourceId: "text" },
        },
      },
      {
        type: "resource",
        resource: {
          uri: "https://example.com/blob",
          blob: "YmxvYg==",
        },
      },
    ],
  };
  const app = {
    async callServerTool() {
      return { content: [], structuredContent };
    },
  };

  const response = await getContentBlocks(undefined, app);
  assert.equal(response.error, undefined);
  assert.equal(response.result.result.length, 6);
  assert.equal(response.result.result[0].text, "visible");
  assert.equal(response.result.result[1].annotations, null);
  assert.equal(response.result.result[3].icons[0].theme, "dark");
  assert.equal(response.result.result[4].resource.text, "resource text");
  assert.equal(response.result.result[5].resource.blob, "YmxvYg==");
  assert.notEqual(response.result, structuredContent);
});

test("rejects malformed nested MCP content blocks", async () => {
  const getContentBlocks = await contentBlocksTool();
  const app = {
    async callServerTool() {
      return {
        content: [],
        structuredContent: {
          result: [
            {
              type: "resource",
              resource: {
                uri: "https://example.com/blob",
                blob: 42,
              },
            },
          ],
        },
      };
    },
  };

  const response = await getContentBlocks(undefined, app);
  assert.equal(response.result, undefined);
  assert(response.error instanceof ZodError);
});

test("returns the complete successful result for raw generated tools", async () => {
  const callRaw = createGeneratedRawTool("call-raw");
  const rawResult = {
    content: [
      { type: "text", text: "visible" },
      { type: "image", data: "example", mimeType: "image/png" },
    ],
    structuredContent: { value: "unvalidated" },
    _meta: { private: true },
  };
  const app = {
    async callServerTool() {
      return rawResult;
    },
  };

  const response = await callRaw({ source: "explicit" }, app);
  assert.deepEqual(response, { result: rawResult, error: undefined });
  assert.equal(response.result, rawResult);
});

test("normalizes MCP errors for raw generated tools", async () => {
  const callRaw = createGeneratedRawTool("call-raw");
  const rawError = {
    content: [{ type: "text", text: "raw failure" }],
    isError: true,
  };
  const app = {
    async callServerTool() {
      return rawError;
    },
  };

  const response = await callRaw({}, app);
  assert.equal(response.result, undefined);
  assert(response.error instanceof McpToolError);
  assert.equal(response.error.message, "raw failure");
  assert.equal(response.error.result, rawError);
});

describe("returns Zod errors for malformed or missing structured output", () => {
  test("malformed", async () => {
    const app = {
      async callServerTool() {
        return { content: [], structuredContent: { value: 42 } };
      },
    };
    const response = await getValue({}, app);
    assert.equal(response.result, undefined);
    assert(response.error instanceof ZodError);
  });

  test("missing", async () => {
    const app = {
      async callServerTool() {
        return { content: [] };
      },
    };
    const response = await getValue({}, app);
    assert.equal(response.result, undefined);
    assert(response.error instanceof ZodError);
  });
});

test("wraps MCP error results with a display-ready message", async () => {
  const rawError = {
    content: [
      { type: "text", text: "first failure" },
      { type: "image", data: "example", mimeType: "image/png" },
      { type: "text", text: "second failure" },
    ],
    isError: true,
    _meta: { requestId: "example" },
  };
  const app = {
    async callServerTool() {
      return rawError;
    },
  };

  const response = await getValue({}, app);
  assert.equal(response.result, undefined);
  assert(response.error instanceof McpToolError);
  assert.equal(response.error.name, "McpToolError");
  assert.equal(response.error.message, "first failure\nsecond failure");
  assert.equal(response.error.toolName, "get-value");
  assert.equal(response.error.result, rawError);
  assert.equal(response.error.result._meta.requestId, "example");
  assert.equal(response.error.cause, rawError);
});

test("uses a tool-specific fallback for MCP errors without text", async () => {
  const rawError = {
    content: [{ type: "image", data: "example", mimeType: "image/png" }],
    isError: true,
  };
  const app = {
    async callServerTool() {
      return rawError;
    },
  };

  const response = await getValue({}, app);
  assert(response.error instanceof McpToolError);
  assert.equal(response.error.message, 'MCP tool "get-value" returned an error');
  assert.equal(response.error.result, rawError);
});

describe("returns transport and context failures instead of rejecting", () => {
  test("transport Error", async () => {
    const failure = new Error("transport failed");
    const app = {
      async callServerTool() {
        throw failure;
      },
    };
    const response = await getValue({}, app);
    assert.equal(response.result, undefined);
    assert.equal(response.error, failure);
  });

  test("non-Error rejection", async () => {
    const app = {
      async callServerTool() {
        throw "protocol failed";
      },
    };
    const response = await getValue({}, app);
    assert.equal(response.result, undefined);
    assert(response.error instanceof Error);
    assert.equal(response.error.message, "protocol failed");
  });

  test("missing Widget context", async () => {
    const response = await getValue({});
    assert.equal(response.result, undefined);
    assert(response.error instanceof Error);
    assert.match(response.error.message, /active connected <Widget>/u);
  });
});

test("captures the opening tool result before Widget children mount", async () => {
  const rawResult = {
    content: [{ type: "text", text: "opening" }],
    structuredContent: { value: "opening" },
    _meta: { requestId: "opening" },
  };
  let resultState;
  let inputHookCalls = 0;
  let resultHookCalls = 0;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      restore.emit(this, "toolinput", { arguments: { value: "input" } });
      restore.emit(this, "toolresult", rawResult);
    },
    methods: {
      getHostContext() {
        return {};
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: { name: "Opening result", version: "1.0.0" },
            hooks: {
              toolInput: () => {
                inputHookCalls += 1;
              },
              toolResult: () => {
                resultHookCalls += 1;
              },
            },
          },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    assert.deepEqual(resultState.data, { value: "opening" });
    assert.equal(resultState.rawResult, rawResult);
    assert.equal(resultState.error, undefined);
    assert.equal(resultState.status, "success");
    assert.equal(resultState.isLoading, false);
    assert.equal(resultState.isFetching, false);
    assert.equal(resultState.isSuccess, true);
    assert.equal(resultState.isError, false);
    assert.equal(inputHookCalls, 1);
    assert.equal(resultHookCalls, 1);
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("keeps an unresolved opening result pending and consumes later results", async () => {
  let app;
  let resultState;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      app = this;
    },
    methods: {
      getHostContext() {
        return { toolInfo: { tool: { name: "get-value" } } };
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Pending result", version: "1.0.0" } },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    assert.equal(resultState.status, "pending");
    assert.equal(resultState.isLoading, true);
    assert.equal(resultState.isFetching, true);

    const rawResult = {
      content: [],
      structuredContent: { value: "later" },
    };
    await act(async () => {
      restore.emit(app, "toolresult", rawResult);
    });
    assert.deepEqual(resultState.data, { value: "later" });
    assert.equal(resultState.rawResult, rawResult);
    assert.equal(resultState.status, "success");
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

describe("normalizes opening raw, error, invalid, cancellation, and mismatch states", () => {
  async function renderOpening({ source, toolName, event, params }) {
    let resultState;
    let renderer;
    let calls = 0;
    const restore = stubApp({
      connect: async function connect() {
        restore.emit(this, event, params);
      },
      call: async () => {
        calls += 1;
        return { content: [], structuredContent: { value: "called" } };
      },
      methods: {
        getHostContext() {
          return { toolInfo: { tool: { name: toolName } } };
        },
      },
    });
    try {
      await act(async () => {
        renderer = create(
          createElement(
            Widget,
            { metadata: { name: "Opening state", version: "1.0.0" } },
            createElement(ResultProbe, {
              source,
              rendered: (state) => {
                resultState = state;
              },
            }),
          ),
        );
      });
      return {
        get resultState() {
          return resultState;
        },
        get calls() {
          return calls;
        },
        async cleanup() {
          if (renderer !== undefined) {
            await act(async () => renderer.unmount());
          }
          restore();
        },
      };
    } catch (error) {
      restore();
      throw error;
    }
  }

  test("raw", async () => {
    const rawTool = createGeneratedRawTool("raw-opening");
    const rawResult = {
      content: [{ type: "text", text: "raw" }],
      structuredContent: { unvalidated: true },
      _meta: { private: true },
    };
    const view = await renderOpening({
      source: rawTool,
      toolName: "raw-opening",
      event: "toolresult",
      params: rawResult,
    });
    try {
      assert.equal(view.resultState.data, rawResult);
      assert.equal(view.resultState.rawResult, rawResult);
      assert.equal(view.resultState.status, "success");
    } finally {
      await view.cleanup();
    }
  });

  test("MCP error", async () => {
    const rawError = {
      content: [{ type: "text", text: "opening failed" }],
      isError: true,
    };
    const view = await renderOpening({
      source: getValue,
      toolName: "get-value",
      event: "toolresult",
      params: rawError,
    });
    try {
      assert(view.resultState.error instanceof McpToolError);
      assert.equal(view.resultState.rawResult, rawError);
      assert.equal(view.resultState.status, "error");
    } finally {
      await view.cleanup();
    }
  });

  test("invalid structured output", async () => {
    const malformed = { content: [], structuredContent: { value: 42 } };
    const view = await renderOpening({
      source: getValue,
      toolName: "get-value",
      event: "toolresult",
      params: malformed,
    });
    try {
      assert(view.resultState.error instanceof ZodError);
      assert.equal(view.resultState.rawResult, malformed);
    } finally {
      await view.cleanup();
    }
  });

  test("cancellation", async () => {
    const view = await renderOpening({
      source: getValue,
      toolName: "get-value",
      event: "toolcancelled",
      params: { reason: "user action" },
    });
    try {
      assert(view.resultState.error instanceof McpToolCancelledError);
      assert.equal(view.resultState.error.toolName, "get-value");
      assert.equal(view.resultState.error.reason, "user action");
      assert.equal(view.resultState.isFetching, false);
    } finally {
      await view.cleanup();
    }
  });

  test("source mismatch", async () => {
    const view = await renderOpening({
      source: getValue,
      toolName: "another-tool",
      event: "toolresult",
      params: { content: [], structuredContent: { value: "wrong" } },
    });
    try {
      assert.match(view.resultState.error.message, /expected opening tool/u);
      let response;
      await act(async () => {
        response = await view.resultState.execute({ value: "ignored" });
      });
      assert.match(response.error.message, /expected opening tool/u);
      assert.equal(view.calls, 0);
    } finally {
      await view.cleanup();
    }
  });
});

test("executes with reusable typed input and preserves stale data", async () => {
  const calls = [];
  const pending = [];
  let resultState;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      restore.emit(this, "toolinput", { arguments: { value: "opening-input" } });
      restore.emit(this, "toolresult", {
        content: [],
        structuredContent: { value: "opening-data" },
      });
    },
    call: ({ arguments: input }) => {
      calls.push(input);
      return new Promise((resolve) => pending.push(resolve));
    },
    methods: {
      getHostContext() {
        return { toolInfo: { tool: { name: "get-value" } } };
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Execute result", version: "1.0.0" } },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    let firstPromise;
    await act(async () => {
      firstPromise = resultState.execute();
      await Promise.resolve();
    });
    assert.deepEqual(calls[0], { value: "opening-input" });
    assert.deepEqual(resultState.data, { value: "opening-data" });
    assert.equal(resultState.isLoading, false);
    assert.equal(resultState.isFetching, true);
    assert.equal(resultState.status, "success");

    await act(async () => {
      pending.shift()({
        content: [],
        structuredContent: { value: "first-execution" },
      });
      await firstPromise;
    });
    assert.deepEqual(resultState.data, { value: "first-execution" });

    let explicitPromise;
    await act(async () => {
      explicitPromise = resultState.execute({ value: "replacement" });
      await Promise.resolve();
    });
    assert.deepEqual(calls[1], { value: "replacement" });
    await act(async () => {
      pending.shift()({
        content: [],
        structuredContent: { value: 42 },
        _meta: { requestId: "invalid" },
      });
      await explicitPromise;
    });
    assert.deepEqual(resultState.data, { value: "first-execution" });
    assert(resultState.error instanceof ZodError);
    assert.equal(resultState.rawResult._meta.requestId, "invalid");
    assert.equal(resultState.status, "error");

    let retryPromise;
    await act(async () => {
      retryPromise = resultState.execute();
      await Promise.resolve();
    });
    assert.deepEqual(calls[2], { value: "replacement" });
    assert.equal(resultState.error, undefined);
    assert.equal(resultState.isFetching, true);
    await act(async () => {
      pending.shift()({
        content: [],
        structuredContent: { value: "retry" },
      });
      await retryPromise;
    });
    assert.deepEqual(resultState.data, { value: "retry" });
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("execute(undefined) clears cached optional input", async () => {
  const requests = [];
  let app;
  let resultState;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      app = this;
      restore.emit(this, "toolinput", { arguments: { value: "opening-input" } });
      restore.emit(this, "toolresult", {
        content: [],
        structuredContent: { value: "opening-data" },
      });
    },
    call: async (request) => {
      requests.push(request);
      return {
        content: [],
        structuredContent: { value: `called-${requests.length}` },
      };
    },
    methods: {
      getHostContext() {
        return { toolInfo: { tool: { name: "get-value" } } };
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Clear cached input", version: "1.0.0" } },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    await act(async () => {
      await resultState.execute();
    });
    assert.deepEqual(requests[0], {
      name: "get-value",
      arguments: { value: "opening-input" },
    });

    await act(async () => {
      await resultState.execute(undefined);
    });
    assert.deepEqual(requests[1], { name: "get-value" });

    await act(async () => {
      restore.emit(app, "toolinput", {
        arguments: { value: "late-opening-input" },
      });
    });

    await act(async () => {
      await resultState.execute();
    });
    assert.deepEqual(requests[2], { name: "get-value" });
    assert.deepEqual(resultState.data, { value: "called-3" });
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("picks up late opening input after an early execute", async () => {
  const calls = [];
  let app;
  let resultState;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      app = this;
      restore.emit(this, "toolresult", {
        content: [],
        structuredContent: { value: "opening-data" },
      });
    },
    call: async ({ arguments: input }) => {
      calls.push(input);
      return {
        content: [],
        structuredContent: { value: `called-${calls.length}` },
      };
    },
    methods: {
      getHostContext() {
        return { toolInfo: { tool: { name: "get-value" } } };
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Late opening input", version: "1.0.0" } },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    assert.deepEqual(resultState.data, { value: "opening-data" });

    await act(async () => {
      await resultState.execute();
    });
    assert.equal(calls[0], undefined);

    await act(async () => {
      restore.emit(app, "toolinput", { arguments: { value: "opening-input" } });
    });

    await act(async () => {
      await resultState.execute();
    });
    assert.deepEqual(calls[1], { value: "opening-input" });
    assert.deepEqual(resultState.data, { value: "called-2" });
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("recomputes opening mismatch after host context arrives", async () => {
  let hostContext = {};
  let app;
  let resultState;
  let renderer;
  let calls = 0;
  const restore = stubApp({
    connect: async function connect() {
      app = this;
      restore.emit(this, "toolresult", {
        content: [],
        structuredContent: { value: "opening" },
      });
    },
    call: async () => {
      calls += 1;
      return { content: [], structuredContent: { value: "called" } };
    },
    methods: {
      getHostContext() {
        return hostContext;
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Late mismatch", version: "1.0.0" } },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    assert.deepEqual(resultState.data, { value: "opening" });
    assert.equal(resultState.status, "success");

    await act(async () => {
      hostContext = { toolInfo: { tool: { name: "another-tool" } } };
      restore.emit(app, "hostcontextchanged", hostContext);
    });

    assert.match(resultState.error.message, /expected opening tool/u);
    assert.equal(resultState.status, "error");
    assert.equal(resultState.data, undefined);

    let response;
    await act(async () => {
      response = await resultState.execute({ value: "ignored" });
    });
    assert.match(response.error.message, /expected opening tool/u);
    assert.equal(calls, 0);
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("keeps only the latest execution in hook state", async () => {
  const pending = new Map();
  let resultState;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      restore.emit(this, "toolresult", {
        content: [],
        structuredContent: { value: "opening" },
      });
    },
    call: ({ arguments: input }) =>
      new Promise((resolve) => pending.set(input.value, resolve)),
    methods: {
      getHostContext() {
        return { toolInfo: { tool: { name: "get-value" } } };
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Latest result", version: "1.0.0" } },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    let olderPromise;
    let newerPromise;
    await act(async () => {
      olderPromise = resultState.execute({ value: "older" });
      newerPromise = resultState.execute({ value: "newer" });
      await Promise.resolve();
    });
    await act(async () => {
      pending.get("newer")({
        content: [],
        structuredContent: { value: "newer" },
      });
      await newerPromise;
    });
    assert.deepEqual(resultState.data, { value: "newer" });
    assert.equal(resultState.isFetching, false);

    let olderResult;
    await act(async () => {
      pending.get("older")({
        content: [],
        structuredContent: { value: "older" },
      });
      olderResult = await olderPromise;
    });
    assert.deepEqual(olderResult.result, { value: "older" });
    assert.deepEqual(resultState.data, { value: "newer" });
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("keeps direct generated calls independent from hook state", async () => {
  let resultState;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      restore.emit(this, "toolresult", {
        content: [],
        structuredContent: { value: "opening" },
      });
    },
    call: async () => ({
      content: [],
      structuredContent: { value: "direct" },
    }),
    methods: {
      getHostContext() {
        return { toolInfo: { tool: { name: "get-value" } } };
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Independent result", version: "1.0.0" } },
          createElement(ResultProbe, {
            source: getValue,
            rendered: (state) => {
              resultState = state;
            },
          }),
        ),
      );
    });

    assert.deepEqual(await getValue({ value: "direct" }), {
      result: { value: "direct" },
      error: undefined,
    });
    assert.deepEqual(resultState.data, { value: "opening" });
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("does not duplicate tool result listeners across Strict Mode setup", async () => {
  let app;
  let resultState;
  let resultHookCalls = 0;
  let renderer;
  const restore = stubApp({
    connect: async function connect() {
      app = this;
    },
    methods: {
      getHostContext() {
        return { toolInfo: { tool: { name: "get-value" } } };
      },
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          StrictMode,
          null,
          createElement(
            Widget,
            {
              metadata: { name: "Strict result", version: "1.0.0" },
              hooks: {
                toolResult: () => {
                  resultHookCalls += 1;
                },
              },
            },
            createElement(ResultProbe, {
              source: getValue,
              rendered: (state) => {
                resultState = state;
              },
            }),
          ),
        ),
      );
    });

    await act(async () => {
      restore.emit(app, "toolresult", {
        content: [],
        structuredContent: { value: "strict" },
      });
    });
    assert.equal(resultHookCalls, 1);
    assert.deepEqual(resultState.data, { value: "strict" });
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("requires useToolResult to run within Widget context", async () => {
  await assert.rejects(
    async () => {
      await act(async () => {
        create(
          createElement(ResultProbe, {
            source: getValue,
            rendered: () => {},
          }),
        );
      });
    },
    /useToolResult must be used within a connected <Widget>/u,
  );
});

test("uses the active Widget after connection and clears it on teardown", async () => {
  let app;
  let renderer;
  let afterResult;
  let teardownCalled = false;
  const restore = stubApp({
    connect: async function connect() {
      app = this;
    },
    call: async ({ arguments: input }) => ({
      content: [],
      structuredContent: { value: input.value },
    }),
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: { name: "Lifecycle test", version: "1.0.0" },
            hooks: {
              after: async () => {
                afterResult = await getValue({ value: "after" });
              },
              teardown: () => {
                teardownCalled = true;
                return {};
              },
            },
          },
          createElement("span", null, "connected"),
        ),
      );
    });

    assert.deepEqual(afterResult, {
      result: { value: "after" },
      error: undefined,
    });
    await act(async () => {
      await app.onteardown({}, {});
    });
    assert.equal(teardownCalled, true);
    const afterTeardown = await getValue({ value: "teardown" });
    assert.equal(afterTeardown.result, undefined);
    assert(afterTeardown.error instanceof Error);
    assert.match(afterTeardown.error.message, /active connected <Widget>/u);
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("forwards common app helpers through the active Widget", async () => {
  let app;
  let renderer;
  const calls = {};
  const results = Object.fromEntries(
    [
      "sendMessage",
      "sendLog",
      "updateModelContext",
      "openLink",
      "downloadFile",
      "requestDisplayMode",
      "requestTeardown",
    ].map((name) => [name, Promise.resolve({ method: name })]),
  );
  const methods = Object.fromEntries(
    Object.keys(results).map((name) => [
      name,
      function method(...args) {
        calls[name] = { app: this, args };
        return results[name];
      },
    ]),
  );
  const restore = stubApp({
    connect: async function connect() {
      app = this;
    },
    methods,
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "App helpers test", version: "1.0.0" } },
          createElement("span", null, "connected"),
        ),
      );
    });

    const message = {
      role: "user",
      content: [{ type: "text", text: "hello" }],
    };
    const log = { level: "info", data: "hello" };
    const modelContext = {
      content: [{ type: "text", text: "context" }],
    };
    const link = { url: "https://example.com" };
    const download = {
      contents: [
        {
          type: "resource_link",
          uri: "https://example.com/file",
          name: "file",
        },
      ],
    };
    const displayMode = { mode: "fullscreen" };
    const teardown = {};
    const requestOptions = { timeout: 1_000 };

    assert.equal(sendMessage(message, requestOptions), results.sendMessage);
    assert.equal(sendLog(log), results.sendLog);
    assert.equal(
      updateModelContext(modelContext, requestOptions),
      results.updateModelContext,
    );
    assert.equal(openLink(link, requestOptions), results.openLink);
    assert.equal(downloadFile(download, requestOptions), results.downloadFile);
    assert.equal(
      requestDisplayMode(displayMode, requestOptions),
      results.requestDisplayMode,
    );
    assert.equal(requestTeardown(teardown), results.requestTeardown);

    assert.deepEqual(calls, {
      sendMessage: { app, args: [message, requestOptions] },
      sendLog: { app, args: [log] },
      updateModelContext: { app, args: [modelContext, requestOptions] },
      openLink: { app, args: [link, requestOptions] },
      downloadFile: { app, args: [download, requestOptions] },
      requestDisplayMode: { app, args: [displayMode, requestOptions] },
      requestTeardown: { app, args: [teardown] },
    });

    await act(async () => renderer.unmount());
    renderer = undefined;
    assert.throws(
      () => sendMessage(message),
      /active connected <Widget>/u,
    );
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("clears the active Widget on unmount", async () => {
  let renderer;
  const restore = stubApp({
    call: async () => ({
      content: [],
      structuredContent: { value: "mounted" },
    }),
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Unmount test", version: "1.0.0" } },
          createElement("span", null, "connected"),
        ),
      );
    });
    assert.deepEqual(await getValue({}), {
      result: { value: "mounted" },
      error: undefined,
    });

    await act(async () => renderer.unmount());
    renderer = undefined;
    const response = await getValue({});
    assert.equal(response.result, undefined);
    assert(response.error instanceof Error);
    assert.match(response.error.message, /active connected <Widget>/u);
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("clears the active Widget when initialization fails", async () => {
  let renderer;
  const restore = stubApp({});
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: { name: "Failure test", version: "1.0.0" },
            hooks: {
              after: () => {
                throw new Error("after failed");
              },
            },
            error: (error) => createElement("span", null, error.message),
          },
          createElement("span", null, "connected"),
        ),
      );
    });

    assert.match(JSON.stringify(renderer.toJSON()), /after failed/u);
    const response = await getValue({ value: "failure" });
    assert.equal(response.result, undefined);
    assert(response.error instanceof Error);
    assert.match(response.error.message, /active connected <Widget>/u);
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("rejects a second concurrently connected Widget", async () => {
  let renderer;
  const restore = stubApp({});
  try {
    const widget = (name) =>
      createElement(
        Widget,
        {
          metadata: { name, version: "1.0.0" },
          error: (error) => createElement("span", null, error.message),
        },
        createElement("span", null, `${name} connected`),
      );
    await act(async () => {
      renderer = create(
        createElement("div", null, widget("first"), widget("second")),
      );
    });
    assert.match(
      JSON.stringify(renderer.toJSON()),
      /Only one connected <Widget> can be active at a time/u,
    );
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("forwards every optional Widget hook and exposes useWidget", async () => {
  let app;
  let hookApp;
  let renderer;
  const calls = [];
  function WidgetProbe() {
    hookApp = useWidget();
    return createElement("span", null, "connected");
  }
  const restore = stubApp({
    connect: async function connect() {
      app = this;
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: {
              name: "All hooks",
              version: "1.0.0",
              title: "All Widget hooks",
              capabilities: { tools: {} },
              autoResize: false,
              strict: true,
            },
            hooks: {
              toolInput: () => calls.push("input"),
              toolInputPartial: () => calls.push("partial"),
              toolResult: () => calls.push("result"),
              toolCancelled: () => calls.push("cancelled"),
              hostContextChanged: () => calls.push("context"),
            },
          },
          createElement(WidgetProbe),
        ),
      );
    });
    assert.equal(hookApp, app);
    await act(async () => {
      restore.emit(app, "toolinput", { arguments: {} });
      restore.emit(app, "toolinputpartial", { arguments: {} });
      restore.emit(app, "toolresult", { content: [] });
      restore.emit(app, "toolcancelled", { reason: "cancelled" });
      restore.emit(app, "hostcontextchanged", {});
    });
    assert.deepEqual(calls, ["input", "partial", "result", "cancelled", "context"]);
    assert.deepEqual(await app.onteardown({}, {}), {});
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("uses the default error logger when no error hook is supplied", async () => {
  let app;
  let renderer;
  const logged = [];
  const originalError = console.error;
  console.error = (...args) => logged.push(args);
  const restore = stubApp({
    connect: async function connect() {
      app = this;
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          { metadata: { name: "Logger", version: "1.0.0" } },
          createElement("span", null, "connected"),
        ),
      );
    });
    const error = new Error("logged");
    app.onerror(error);
    assert.deepEqual(logged, [[error]]);
  } finally {
    console.error = originalError;
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("tolerates an already-connected App and custom fallback", async () => {
  let renderer;
  let release;
  const before = new Promise((resolve) => {
    release = resolve;
  });
  const restore = stubApp({
    connect: async () => {
      throw new Error("App already connected");
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: { name: "Existing", version: "1.0.0" },
            fallback: createElement("span", null, "Please wait"),
            hooks: { before: () => before },
          },
          createElement("span", null, "connected"),
        ),
      );
    });
    assert.equal(renderer.toJSON(), "Please wait");
    await act(async () => release());
    assert.equal(renderer.toJSON(), "connected");
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test.each([
  ["before", "before failure"],
  ["connect", "connect failure"],
])("renders the default error UI for %s failures", async (phase, message) => {
  let renderer;
  const restore = stubApp({
    connect: async () => {
      if (phase === "connect") throw message;
    },
  });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: { name: "Failure UI", version: "1.0.0" },
            hooks: phase === "before" ? { before: () => { throw message; } } : undefined,
          },
          createElement("span", null, "connected"),
        ),
      );
    });
    assert.match(renderer.toJSON(), new RegExp(`ERROR: ${message}`, "u"));
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    restore();
  }
});

test("renders a static error element", async () => {
  let renderer;
  const restore = stubApp({ connect: async () => { throw new Error("failed"); } });
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: { name: "Static error", version: "1.0.0" },
            error: createElement("span", null, "static failure"),
          },
          createElement("span", null, "connected"),
        ),
      );
    });
    assert.equal(renderer.toJSON(), "static failure");
  } finally {
    if (renderer !== undefined) await act(async () => renderer.unmount());
    restore();
  }
});

test.each(["before", "connect", "after"])(
  "does not activate after unmount during %s",
  async (phase) => {
    let renderer;
    let release;
    const blocked = new Promise((resolve) => {
      release = resolve;
    });
    const restore = stubApp({
      connect: phase === "connect" ? () => blocked : async () => {},
    });
    try {
      await act(async () => {
        renderer = create(
          createElement(
            Widget,
            {
              metadata: { name: `Blocked ${phase}`, version: "1.0.0" },
              hooks: {
                ...(phase === "before" ? { before: () => blocked } : {}),
                ...(phase === "after" ? { after: () => blocked } : {}),
              },
            },
            createElement("span", null, "connected"),
          ),
        );
      });
      await act(async () => renderer.unmount());
      renderer = undefined;
      await act(async () => release());
      const response = await getValue({});
      assert.match(response.error?.message ?? "", /active connected <Widget>/u);
    } finally {
      if (renderer !== undefined) await act(async () => renderer.unmount());
      restore();
    }
  },
);

test("mountWidget validates the root and reuses its React root", async () => {
  document.body.replaceChildren();
  assert.throws(() => mountWidget(() => createElement("span", null, "first")), /root #root was not found/u);
  const root = document.createElement("div");
  root.id = "root";
  document.body.append(root);
  await act(async () => {
    mountWidget(() => createElement("span", null, "first"));
  });
  assert.equal(root.textContent, "first");
  await act(async () => {
    mountWidget(() => createElement("span", null, "second"));
  });
  assert.equal(root.textContent, "second");
});
