import assert from "node:assert/strict";
import test from "node:test";

import { App } from "@modelcontextprotocol/ext-apps";
import { StrictMode, createElement } from "react";
import { act, create } from "react-test-renderer";

import {
  Widget,
  createCallTool,
  createUseTool,
  defineToolRegistry,
} from "../dist/index.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const tools = defineToolRegistry({
  raw: "raw",
  structured: "structured",
});
const callTool = createCallTool(tools);
const useTool = createUseTool(tools);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function renderHook(name, input, callServerTool, { strict = false } = {}) {
  const originalConnect = App.prototype.connect;
  const originalClose = App.prototype.close;
  const originalCall = App.prototype.callServerTool;
  App.prototype.connect = async () => {};
  App.prototype.close = async () => {};
  App.prototype.callServerTool = callServerTool;

  let state;
  let currentInput = input;
  function Probe() {
    state = useTool(name, currentInput);
    return null;
  }

  function element() {
    const widget = createElement(
      Widget,
      { metadata: { name: "Runtime test", version: "1.0.0" } },
      createElement(Probe),
    );
    return strict ? createElement(StrictMode, null, widget) : widget;
  }

  let renderer;
  await act(async () => {
    renderer = create(element());
  });
  assert(state);
  return {
    get state() {
      return state;
    },
    async setInput(nextInput) {
      currentInput = nextInput;
      await act(async () => renderer.update(element()));
    },
    async close() {
      await act(async () => renderer.unmount());
      App.prototype.connect = originalConnect;
      App.prototype.close = originalClose;
      App.prototype.callServerTool = originalCall;
    },
  };
}

test("automatically calls a structured tool once and exposes request state", async () => {
  let calls = 0;
  const hook = await renderHook(
    "structured",
    { value: 7 },
    async ({ arguments: input }) => {
      calls += 1;
      return { content: [], structuredContent: { value: input.value } };
    },
  );
  try {
    assert.equal(calls, 1);
    assert.deepEqual(hook.state.data, { value: 7 });
    assert.equal(hook.state.error, null);
    assert.equal(hook.state.status, "success");
    assert.equal(hook.state.isIdle, false);
    assert.equal(hook.state.isLoading, false);
    assert.equal(hook.state.isSuccess, true);
    assert.equal(hook.state.isError, false);
  } finally {
    await hook.close();
  }
});

test("exposes loading state and raw results during the automatic call", async () => {
  const response = deferred();
  const rawResult = { content: [{ type: "text", text: "raw" }] };
  const hook = await renderHook("raw", undefined, async (request) => {
    assert.equal("arguments" in request, false);
    return response.promise;
  });
  try {
    assert.equal(hook.state.status, "pending");
    assert.equal(hook.state.isLoading, true);
    assert.equal(hook.state.data, undefined);
    response.resolve(rawResult);
    await act(async () => {
      await response.promise;
    });
    assert.equal(hook.state.data, rawResult);
    assert.equal(hook.state.isSuccess, true);
  } finally {
    await hook.close();
  }
});

test("does not refetch on input changes and mutate uses the latest input", async () => {
  const inputs = [];
  const hook = await renderHook(
    "structured",
    { value: 1 },
    async ({ arguments: input }) => {
      inputs.push(input.value);
      return { content: [], structuredContent: { value: input.value } };
    },
  );
  try {
    await hook.setInput({ value: 2 });
    assert.deepEqual(inputs, [1]);
    assert.deepEqual(hook.state.data, { value: 1 });

    let returned;
    await act(async () => {
      returned = await hook.state.mutate();
    });
    assert.deepEqual(returned, { value: 2 });
    assert.deepEqual(inputs, [1, 2]);
    assert.deepEqual(hook.state.data, { value: 2 });
  } finally {
    await hook.close();
  }
});

test("does not duplicate the automatic call during Strict Mode effect replay", async () => {
  let calls = 0;
  const hook = await renderHook(
    "structured",
    {},
    async () => {
      calls += 1;
      return { content: [], structuredContent: { calls } };
    },
    { strict: true },
  );
  try {
    assert.equal(calls, 1);
    assert.deepEqual(hook.state.data, { calls: 1 });
  } finally {
    await hook.close();
  }
});

test("turns MCP failures and missing structured content into hook errors", async (t) => {
  await t.test("MCP error content", async () => {
    const hook = await renderHook("structured", {}, async () => ({
      content: [
        { type: "text", text: "first" },
        { type: "text", text: "second" },
      ],
      isError: true,
    }));
    try {
      assert.match(hook.state.error.message, /first\nsecond/u);
      assert.equal(hook.state.status, "error");
      assert.equal(hook.state.isError, true);
      await act(async () => {
        await assert.rejects(hook.state.mutate(), /first\nsecond/u);
      });
    } finally {
      await hook.close();
    }
  });

  await t.test("missing structured content", async () => {
    const hook = await renderHook("structured", {}, async () => ({ content: [] }));
    try {
      assert.match(hook.state.error.message, /returned no structuredContent/u);
      assert.equal(hook.state.isError, true);
    } finally {
      await hook.close();
    }
  });
});

test("only the newest concurrent mutation updates hook state", async () => {
  const first = deferred();
  const second = deferred();
  const hook = await renderHook(
    "structured",
    { call: 0 },
    ({ arguments: input }) => {
      if (input.call === 0) {
        return Promise.resolve({ content: [], structuredContent: { call: 0 } });
      }
      return input.call === 1 ? first.promise : second.promise;
    },
  );
  try {
    await hook.setInput({ call: 1 });
    let firstPromise;
    await act(async () => {
      firstPromise = hook.state.mutate();
    });
    await hook.setInput({ call: 2 });
    let secondPromise;
    await act(async () => {
      secondPromise = hook.state.mutate();
    });
    assert.equal(hook.state.isLoading, true);

    second.resolve({ content: [], structuredContent: { call: 2 } });
    await act(async () => {
      assert.deepEqual(await secondPromise, { call: 2 });
    });
    assert.deepEqual(hook.state.data, { call: 2 });

    first.resolve({ content: [], structuredContent: { call: 1 } });
    await act(async () => {
      assert.deepEqual(await firstPromise, { call: 1 });
    });
    assert.deepEqual(hook.state.data, { call: 2 });
    assert.equal(hook.state.isSuccess, true);
  } finally {
    await hook.close();
  }
});

test("ignores an in-flight mutation after unmount", async () => {
  const response = deferred();
  const hook = await renderHook(
    "structured",
    { value: "initial" },
    ({ arguments: input }) => {
      if (input.value === "initial") {
        return Promise.resolve({ content: [], structuredContent: input });
      }
      return response.promise;
    },
  );
  await hook.setInput({ value: "late" });
  let promise;
  await act(async () => {
    promise = hook.state.mutate();
  });
  await hook.close();
  response.resolve({ content: [], structuredContent: { value: "late" } });
  assert.deepEqual(await promise, { value: "late" });
});

test("callTool accepts an explicit app without an active Widget", async () => {
  await assert.rejects(
    callTool("structured", { source: "before" }),
    /active connected <Widget>/u,
  );

  const app = {
    async callServerTool({ arguments: input }) {
      return { content: [], structuredContent: { source: input.source } };
    },
  };

  assert.deepEqual(await callTool("structured", { source: "explicit" }, { app }), {
    source: "explicit",
  });

  await assert.rejects(
    callTool("structured", { source: "after" }),
    /active connected <Widget>/u,
  );
});

test("useTool accepts an explicit app without Widget context", async () => {
  const app = {
    async callServerTool({ arguments: input }) {
      return { content: [], structuredContent: { source: input.source } };
    },
  };

  let state;
  function Probe() {
    state = useTool("structured", { source: "explicit" }, { app });
    return null;
  }

  let renderer;
  await act(async () => {
    renderer = create(createElement(Probe));
  });
  try {
    assert.deepEqual(state.data, { source: "explicit" });
    assert.equal(state.status, "success");
  } finally {
    await act(async () => renderer.unmount());
  }
});

test("callTool uses the active Widget independently without deduplication", async () => {
  await assert.rejects(
    callTool("structured", { source: "before" }),
    /active connected <Widget>/u,
  );

  let calls = 0;
  const hook = await renderHook(
    "structured",
    { source: "hook" },
    async ({ arguments: input }) => {
      calls += 1;
      return {
        content: [],
        structuredContent: { source: input.source, call: calls },
      };
    },
  );
  try {
    assert.deepEqual(hook.state.data, { source: "hook", call: 1 });
    const [first, second] = await Promise.all([
      callTool("structured", { source: "global" }),
      callTool("structured", { source: "global" }),
    ]);
    assert.deepEqual(first, { source: "global", call: 2 });
    assert.deepEqual(second, { source: "global", call: 3 });
    assert.equal(calls, 3);
    assert.deepEqual(hook.state.data, { source: "hook", call: 1 });
  } finally {
    await hook.close();
  }

  await assert.rejects(
    callTool("structured", { source: "after" }),
    /active connected <Widget>/u,
  );
});

test("registers callTool before after hooks and clears it on teardown", async () => {
  const originalConnect = App.prototype.connect;
  const originalClose = App.prototype.close;
  const originalCall = App.prototype.callServerTool;
  let app;
  let teardownCalled = false;
  App.prototype.connect = async function connect() {
    app = this;
  };
  App.prototype.close = async () => {};
  App.prototype.callServerTool = async ({ arguments: input }) => ({
    content: [],
    structuredContent: input,
  });
  let renderer;
  let afterResult;
  try {
    await act(async () => {
      renderer = create(
        createElement(
          Widget,
          {
            metadata: { name: "Lifecycle test", version: "1.0.0" },
            hooks: {
              after: async () => {
                afterResult = await callTool("structured", { phase: "after" });
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
    assert.deepEqual(afterResult, { phase: "after" });
    await act(async () => {
      await app.onteardown({}, {});
    });
    assert.equal(teardownCalled, true);
    await assert.rejects(
      callTool("structured", { phase: "teardown" }),
      /active connected <Widget>/u,
    );
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    App.prototype.connect = originalConnect;
    App.prototype.close = originalClose;
    App.prototype.callServerTool = originalCall;
  }
});

test("clears callTool when Widget initialization fails after connecting", async () => {
  const originalConnect = App.prototype.connect;
  const originalClose = App.prototype.close;
  App.prototype.connect = async () => {};
  App.prototype.close = async () => {};
  let renderer;
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
    await assert.rejects(
      callTool("structured", { phase: "failure" }),
      /active connected <Widget>/u,
    );
  } finally {
    if (renderer !== undefined) {
      await act(async () => renderer.unmount());
    }
    App.prototype.connect = originalConnect;
    App.prototype.close = originalClose;
  }
});

test("rejects a second concurrently connected Widget", async () => {
  const originalConnect = App.prototype.connect;
  const originalClose = App.prototype.close;
  App.prototype.connect = async () => {};
  App.prototype.close = async () => {};
  let renderer;
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
    App.prototype.connect = originalConnect;
    App.prototype.close = originalClose;
  }
});
