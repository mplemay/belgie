import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { App } from "@modelcontextprotocol/ext-apps";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { ZodError } from "zod";

import { McpToolError, Widget } from "../dist/index.js";
import {
  createGeneratedRawTool,
  createGeneratedTool,
} from "../dist/internal.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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
    const pythonMcpV2Tools = JSON.parse(
      await readFile(new URL("./fixtures/python-mcp-v2-tools.json", import.meta.url), "utf8"),
    );
    const contentBlocksSchema = pythonMcpV2Tools.find(
      (tool) => tool.name === "content-blocks",
    )?.outputSchema;
    assert(contentBlocksSchema);
    return createGeneratedTool("content-blocks", contentBlocksSchema);
  })();
  return contentBlocksToolPromise;
}

function stubApp({ connect = async () => {}, close = async () => {}, call }) {
  const originals = {
    connect: App.prototype.connect,
    close: App.prototype.close,
    callServerTool: App.prototype.callServerTool,
  };
  App.prototype.connect = connect;
  App.prototype.close = close;
  if (call !== undefined) {
    App.prototype.callServerTool = call;
  }
  return () => {
    App.prototype.connect = originals.connect;
    App.prototype.close = originals.close;
    App.prototype.callServerTool = originals.callServerTool;
  };
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

test("returns Zod errors for malformed or missing structured output", async (t) => {
  await t.test("malformed", async () => {
    const app = {
      async callServerTool() {
        return { content: [], structuredContent: { value: 42 } };
      },
    };
    const response = await getValue({}, app);
    assert.equal(response.result, undefined);
    assert(response.error instanceof ZodError);
  });

  await t.test("missing", async () => {
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

test("returns transport and context failures instead of rejecting", async (t) => {
  await t.test("transport Error", async () => {
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

  await t.test("non-Error rejection", async () => {
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

  await t.test("missing Widget context", async () => {
    const response = await getValue({});
    assert.equal(response.result, undefined);
    assert(response.error instanceof Error);
    assert.match(response.error.message, /active connected <Widget>/u);
  });
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
