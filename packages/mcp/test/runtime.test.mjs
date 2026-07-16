import assert from "node:assert/strict";
import test from "node:test";

import { App } from "@modelcontextprotocol/ext-apps";
import { createElement } from "react";
import { act, create } from "react-test-renderer";

import { Widget, createUseTool, defineToolRegistry } from "../dist/index.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const tools = defineToolRegistry({
  raw: "raw",
  structured: "structured",
});
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

async function renderHook(name, callServerTool) {
  const originalConnect = App.prototype.connect;
  const originalClose = App.prototype.close;
  const originalCall = App.prototype.callServerTool;
  App.prototype.connect = async () => {};
  App.prototype.close = async () => {};
  App.prototype.callServerTool = callServerTool;

  let state;
  function Probe() {
    state = useTool(name);
    return null;
  }

  const element = createElement(
    Widget,
    { metadata: { name: "Runtime test", version: "1.0.0" } },
    createElement(Probe),
  );

  let renderer;
  await act(async () => {
    renderer = create(element);
  });
  assert(state);
  return {
    get state() {
      return state;
    },
    async close() {
      await act(async () => renderer.unmount());
      App.prototype.connect = originalConnect;
      App.prototype.close = originalClose;
      App.prototype.callServerTool = originalCall;
    },
  };
}

test("stays idle until manually triggered and exposes mutation state", async () => {
  let calls = 0;
  const hook = await renderHook("structured", async ({ arguments: input }) => {
    calls += 1;
    return { content: [], structuredContent: { value: input.value } };
  });
  try {
    assert.equal(calls, 0);
    assert.equal(hook.state.status, "idle");
    assert.equal(hook.state.isIdle, true);
    assert.equal(hook.state.isPending, false);
    assert.equal(hook.state.data, undefined);
    assert.equal(hook.state.error, null);

    let returned;
    await act(async () => {
      returned = await hook.state.mutateAsync({ value: 7 });
    });
    assert.equal(calls, 1);
    assert.deepEqual(returned, { value: 7 });
    assert.deepEqual(hook.state.data, { value: 7 });
    assert.equal(hook.state.status, "success");
    assert.equal(hook.state.isSuccess, true);

    await act(async () => hook.state.reset());
    assert.equal(hook.state.status, "idle");
    assert.equal(hook.state.data, undefined);
  } finally {
    await hook.close();
  }
});

test("supports event-style mutate calls and raw tool results", async () => {
  const response = deferred();
  const rawResult = { content: [{ type: "text", text: "raw" }] };
  const hook = await renderHook("raw", async (request) => {
    assert.equal("arguments" in request, false);
    return response.promise;
  });
  try {
    await act(async () => hook.state.mutate());
    assert.equal(hook.state.status, "pending");
    assert.equal(hook.state.isPending, true);
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

test("turns MCP failures and missing structured content into mutation errors", async (t) => {
  await t.test("MCP error content", async () => {
    const hook = await renderHook("structured", async () => ({
      content: [
        { type: "text", text: "first" },
        { type: "text", text: "second" },
      ],
      isError: true,
    }));
    try {
      await act(async () => {
        await assert.rejects(hook.state.mutateAsync({}), /first\nsecond/u);
      });
      assert.match(hook.state.error.message, /first\nsecond/u);
      assert.equal(hook.state.status, "error");
      assert.equal(hook.state.isError, true);
    } finally {
      await hook.close();
    }
  });

  await t.test("missing structured content", async () => {
    const hook = await renderHook("structured", async () => ({ content: [] }));
    try {
      await act(async () => {
        await assert.rejects(
          hook.state.mutateAsync({}),
          /returned no structuredContent/u,
        );
      });
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
  let calls = 0;
  const hook = await renderHook("structured", ({ arguments: input }) => {
    calls += 1;
    assert.equal(input.call, calls);
    return calls === 1 ? first.promise : second.promise;
  });
  try {
    let firstPromise;
    let secondPromise;
    await act(async () => {
      firstPromise = hook.state.mutateAsync({ call: 1 });
      secondPromise = hook.state.mutateAsync({ call: 2 });
    });
    assert.equal(hook.state.isPending, true);
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

test("ignores in-flight results after reset and unmount", async () => {
  const resetResponse = deferred();
  const resetHook = await renderHook("structured", () => resetResponse.promise);
  let resetPromise;
  try {
    await act(async () => {
      resetPromise = resetHook.state.mutateAsync({});
    });
    await act(async () => resetHook.state.reset());
    resetResponse.resolve({ content: [], structuredContent: { value: "late" } });
    await act(async () => {
      await resetPromise;
    });
    assert.equal(resetHook.state.status, "idle");
    assert.equal(resetHook.state.data, undefined);
  } finally {
    await resetHook.close();
  }

  const unmountResponse = deferred();
  const unmountHook = await renderHook("structured", () => unmountResponse.promise);
  let unmountPromise;
  await act(async () => {
    unmountPromise = unmountHook.state.mutateAsync({});
  });
  await unmountHook.close();
  unmountResponse.resolve({ content: [], structuredContent: { value: "late" } });
  await unmountPromise;
});
