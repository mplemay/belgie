import { act, create, type ReactTestRenderer } from "react-test-renderer";
import type { App } from "@modelcontextprotocol/ext-apps";
import { describe, expect, test, vi } from "vitest";

import {
  createUseToolWithApp,
  type UseToolResult,
} from "../src/use-tool";

interface Tools {
  echo: {
    input: { value: string };
    output: { result: string };
  };
}

type EchoResult = UseToolResult<Tools["echo"]>;
type CallResult = Awaited<ReturnType<App["callServerTool"]>>;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function success(value: string): CallResult {
  return {
    content: [],
    structuredContent: { result: value },
  };
}

describe("createUseTool", () => {
  test("returns typed structured data and tracks loading", async () => {
    let resolveCall: (result: CallResult) => void = () => undefined;
    const callServerTool = vi.fn<App["callServerTool"]>().mockReturnValue(
      new Promise((resolve) => {
        resolveCall = resolve;
      }),
    );
    const useTool = createUseToolWithApp<Tools>(() => ({ callServerTool }));
    let current: EchoResult | undefined;
    let renderer: ReactTestRenderer | undefined;

    function Harness() {
      current = useTool("echo");
      return null;
    }

    await act(async () => {
      renderer = create(<Harness />);
    });

    let promise: Promise<{ result: string }> | undefined;
    await act(async () => {
      promise = current?.call({ value: "hello" });
    });

    expect(current?.loading).toBe(true);
    expect(callServerTool).toHaveBeenCalledWith({ name: "echo", arguments: { value: "hello" } });

    await act(async () => {
      resolveCall(success("hello"));
      await promise;
    });

    expect(current?.data).toEqual({ result: "hello" });
    expect(current?.error).toBeUndefined();
    expect(current?.loading).toBe(false);

    await act(async () => renderer?.unmount());
  });

  test("normalizes MCP errors, stores them, and rethrows", async () => {
    const callServerTool = vi.fn<App["callServerTool"]>().mockResolvedValue({
      content: [{ type: "text", text: "server failed" }],
      isError: true,
    });
    const useTool = createUseToolWithApp<Tools>(() => ({ callServerTool }));
    let current: EchoResult | undefined;
    let renderer: ReactTestRenderer | undefined;

    function Harness() {
      current = useTool("echo");
      return null;
    }

    await act(async () => {
      renderer = create(<Harness />);
    });

    let caught: unknown;
    await act(async () => {
      try {
        await current?.call({ value: "hello" });
      } catch (error: unknown) {
        caught = error;
      }
    });

    expect(caught).toEqual(new Error("server failed"));
    expect(current?.error).toEqual(new Error("server failed"));
    expect(current?.loading).toBe(false);

    await act(async () => renderer?.unmount());
  });

  test("uses latest-call-wins state updates while settling every promise", async () => {
    const resolutions: Array<(result: CallResult) => void> = [];
    const callServerTool = vi.fn<App["callServerTool"]>().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolutions.push(resolve);
        }),
    );
    const useTool = createUseToolWithApp<Tools>(() => ({ callServerTool }));
    let current: EchoResult | undefined;
    let renderer: ReactTestRenderer | undefined;

    function Harness() {
      current = useTool("echo");
      return null;
    }

    await act(async () => {
      renderer = create(<Harness />);
    });

    let first: Promise<{ result: string }> | undefined;
    let second: Promise<{ result: string }> | undefined;
    await act(async () => {
      first = current?.call({ value: "first" });
      second = current?.call({ value: "second" });
    });

    await act(async () => {
      resolutions[1](success("second"));
      await second;
    });
    expect(current?.data).toEqual({ result: "second" });

    await act(async () => {
      resolutions[0](success("first"));
      await first;
    });
    expect(await first).toEqual({ result: "first" });
    expect(current?.data).toEqual({ result: "second" });

    await act(async () => renderer?.unmount());
  });
});
