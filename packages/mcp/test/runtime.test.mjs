import assert from "node:assert/strict";
import test from "node:test";

import { App } from "@modelcontextprotocol/ext-apps";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { ZodError } from "zod";

import { Widget } from "../dist/index.js";
import { createGeneratedTool } from "../dist/internal.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const outputSchema = {
  type: "object",
  properties: { value: { type: "string" } },
  required: ["value"],
  additionalProperties: false,
};
const getValue = createGeneratedTool("get-value", outputSchema);

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

test("preserves raw MCP error results", async () => {
  const rawError = {
    content: [{ type: "text", text: "server failed" }],
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
  assert.equal(response.error, rawError);
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
