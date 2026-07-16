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

  let renderer;
  await act(async () => {
    renderer = create(
      createElement(
        Widget,
        { metadata: { name: "Runtime test", version: "1.0.0" } },
        createElement(Probe),
      ),
    );
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

test("selects structured and raw tool results and resets state", async () => {
  const structured = await renderHook("structured", async ({ arguments: input }) => ({
    content: [],
    structuredContent: { value: input.value },
  }));
  try {
    let returned;
    await act(async () => {
      returned = await structured.state.call({ value: 7 });
    });
    assert.deepEqual(returned, { value: 7 });
    assert.deepEqual(structured.state.result, { value: 7 });
    assert.equal(structured.state.error, null);
    assert.equal(structured.state.loading, false);
    await act(async () => structured.state.reset());
    assert.equal(structured.state.result, null);
  } finally {
    await structured.close();
  }

  const response = { content: [{ type: "text", text: "raw" }] };
  const raw = await renderHook("raw", async () => response);
  try {
    let returned;
    await act(async () => {
      returned = await raw.state.call();
    });
    assert.equal(returned, response);
    assert.equal(raw.state.result, response);
  } finally {
    await raw.close();
  }
});

test("turns MCP failures and missing structured content into hook errors", async (t) => {
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
        await assert.rejects(hook.state.call({}), /first\nsecond/u);
      });
      assert.match(hook.state.error.message, /first\nsecond/u);
      assert.equal(hook.state.loading, false);
    } finally {
      await hook.close();
    }
  });

  await t.test("missing structured content", async () => {
    const hook = await renderHook("structured", async () => ({ content: [] }));
    try {
      await act(async () => {
        await assert.rejects(hook.state.call({}), /returned no structuredContent/u);
      });
      assert.match(hook.state.error.message, /returned no structuredContent/u);
    } finally {
      await hook.close();
    }
  });
});

test("only the newest concurrent call updates hook state", async () => {
  const first = deferred();
  const second = deferred();
  let calls = 0;
  const hook = await renderHook("structured", () => {
    calls += 1;
    return calls === 1 ? first.promise : second.promise;
  });
  try {
    let firstPromise;
    let secondPromise;
    await act(async () => {
      firstPromise = hook.state.call({ call: 1 });
      secondPromise = hook.state.call({ call: 2 });
    });
    assert.equal(hook.state.loading, true);
    second.resolve({ content: [], structuredContent: { call: 2 } });
    await act(async () => {
      assert.deepEqual(await secondPromise, { call: 2 });
    });
    assert.deepEqual(hook.state.result, { call: 2 });
    first.resolve({ content: [], structuredContent: { call: 1 } });
    await act(async () => {
      assert.deepEqual(await firstPromise, { call: 1 });
    });
    assert.deepEqual(hook.state.result, { call: 2 });
    assert.equal(hook.state.loading, false);
  } finally {
    await hook.close();
  }
});
