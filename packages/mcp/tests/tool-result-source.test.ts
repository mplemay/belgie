import assert from "node:assert/strict";

import { describe, test } from "vitest";

import { McpToolCancelledError, McpToolError } from "../src/tool-error.ts";
import {
  createToolResultAdapter,
  getToolResultAdapter,
  normalizeToolCallError,
  TOOL_RESULT_SOURCE,
} from "../src/tool-result-source.ts";

describe("tool errors", () => {
  test("extracts text blocks and preserves the raw MCP error", () => {
    const result = {
      isError: true as const,
      content: [
        { type: "image" as const, data: "", mimeType: "image/png" },
        { type: "text" as const, text: "first" },
        { type: "text" as const, text: "second" },
      ],
    };
    const error = new McpToolError("broken", result);
    assert.equal(error.message, "first\nsecond");
    assert.equal(error.name, "McpToolError");
    assert.equal(error.toolName, "broken");
    assert.equal(error.result, result);
    assert.equal(error.cause, result);
  });

  test("uses fallback error and cancellation messages", () => {
    const result = { isError: true as const, content: [] };
    assert.equal(
      new McpToolError("empty", result).message,
      'MCP tool "empty" returned an error',
    );
    assert.equal(
      new McpToolCancelledError("search").message,
      'MCP tool "search" was cancelled',
    );
    const cancelled = new McpToolCancelledError("search", "user closed");
    assert.equal(cancelled.message, 'MCP tool "search" was cancelled: user closed');
    assert.equal(cancelled.name, "McpToolCancelledError");
    assert.equal(cancelled.toolName, "search");
    assert.equal(cancelled.reason, "user closed");
  });
});

describe("tool result adapters", () => {
  const adapter = createToolResultAdapter<{ value: string }, string>(
    "echo",
    (response) => ({
      result: String(response.structuredContent?.value),
      error: undefined,
    }),
  );

  test("parses successes and MCP failures", () => {
    assert.deepEqual(
      adapter.parse({ content: [], structuredContent: { value: "ok" } }),
      { result: "ok", error: undefined },
    );
    const failure = adapter.parse({ isError: true, content: [] });
    assert.equal(failure.result, undefined);
    assert(failure.error instanceof McpToolError);
  });

  test("executes with and without arguments", async () => {
    const requests: unknown[] = [];
    const app = {
      async callServerTool(request: unknown) {
        requests.push(request);
        return { content: [], structuredContent: { value: "ok" } };
      },
    };
    assert.equal((await adapter.execute({ value: "input" }, app as never)).callResult.result, "ok");
    assert.equal((await adapter.execute(undefined, app as never)).callResult.result, "ok");
    assert.deepEqual(requests, [
      { name: "echo", arguments: { value: "input" } },
      { name: "echo" },
    ]);
  });

  test("normalizes thrown values and invalid sources", async () => {
    const error = new Error("failed");
    assert.equal(normalizeToolCallError(error), error);
    assert.equal(normalizeToolCallError("failed").message, "failed");
    const execution = await adapter.execute(undefined, {
      callServerTool: () => {
        throw "raw failure";
      },
    } as never);
    assert.equal(execution.rawResult, undefined);
    assert.equal(execution.callResult.error?.message, "raw failure");
    assert.throws(
      () => getToolResultAdapter({} as never),
      /requires a generated MCP tool caller/u,
    );
  });

  test("retrieves the branded adapter", () => {
    assert.equal(getToolResultAdapter({ [TOOL_RESULT_SOURCE]: adapter }), adapter);
  });
});
