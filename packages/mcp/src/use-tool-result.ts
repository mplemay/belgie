import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { McpToolCancelledError } from "./tool-error";
import type { RawToolResult, ToolCallError, ToolCallResult } from "./tool-error";
import { errorResult, getToolResultAdapter } from "./tool-result-source";
import type { ToolResultAdapter, ToolResultSource } from "./tool-result-source";
import { useConnectedWidgetContext } from "./widget-context";
import type { WidgetToolLifecycle } from "./widget-context";

export type ToolResultStatus = "pending" | "success" | "error";

export interface ToolResultState<Input extends object, Output> {
  data: Output | undefined;
  error: ToolCallError | undefined;
  rawResult: RawToolResult | undefined;
  status: ToolResultStatus;
  isLoading: boolean;
  isFetching: boolean;
  isSuccess: boolean;
  isError: boolean;
  execute: (input?: Input) => Promise<ToolCallResult<Output>>;
}

interface ResultSnapshot<Output> {
  data: Output | undefined;
  error: ToolCallError | undefined;
  rawResult: RawToolResult | undefined;
  status: ToolResultStatus;
  isFetching: boolean;
}

function sourceMismatchError(expectedName: string, actualName: string | undefined): Error | undefined {
  if (actualName === undefined || actualName === expectedName) {
    return undefined;
  }
  return new Error(
    `useToolResult expected opening tool ${JSON.stringify(expectedName)}, received ${JSON.stringify(actualName)}`,
  );
}

function openingSnapshot<Input extends object, Output>(
  adapter: ToolResultAdapter<Input, Output>,
  lifecycle: WidgetToolLifecycle,
  mismatch: Error | undefined,
): ResultSnapshot<Output> {
  if (mismatch !== undefined) {
    return {
      data: undefined,
      error: mismatch,
      isFetching: false,
      rawResult: lifecycle.rawResult,
      status: "error",
    };
  }
  if (lifecycle.status === "pending") {
    return {
      data: undefined,
      error: undefined,
      isFetching: true,
      rawResult: undefined,
      status: "pending",
    };
  }
  if (lifecycle.status === "cancelled") {
    return {
      data: undefined,
      error: new McpToolCancelledError(adapter.name, lifecycle.cancellationReason),
      isFetching: false,
      rawResult: undefined,
      status: "error",
    };
  }

  const rawResult = lifecycle.rawResult!;
  const callResult = adapter.parse(rawResult);
  return callResult.error === undefined
    ? {
        data: callResult.result,
        error: undefined,
        isFetching: false,
        rawResult,
        status: "success",
      }
    : {
        data: undefined,
        error: callResult.error,
        isFetching: false,
        rawResult,
        status: "error",
      };
}

export function useToolResult<Input extends object, Output>(
  source: ToolResultSource<Input, Output>,
): ToolResultState<Input, Output> {
  const context = useConnectedWidgetContext("useToolResult");
  const adapter = getToolResultAdapter(source);
  const [hostToolName, setHostToolName] = useState<string | undefined>(
    () => context.app.getHostContext()?.toolInfo?.tool.name,
  );
  const mismatch = useMemo(() => sourceMismatchError(adapter.name, hostToolName), [adapter.name, hostToolName]);
  const [snapshot, setSnapshot] = useState<ResultSnapshot<Output>>(() =>
    openingSnapshot(adapter, context.tool, mismatch),
  );
  const hasExecutedRef = useRef(false);
  const hasExplicitInputRef = useRef(false);
  const latestInputRef = useRef<Input | undefined>(context.tool.input as Input | undefined);
  const latestRequestRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      latestRequestRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const syncHostToolName = () => {
      setHostToolName(context.app.getHostContext()?.toolInfo?.tool.name);
    };
    syncHostToolName();
    context.app.addEventListener("hostcontextchanged", syncHostToolName);
    return () => {
      context.app.removeEventListener("hostcontextchanged", syncHostToolName);
    };
  }, [context.app]);

  useEffect(() => {
    if (!hasExplicitInputRef.current && context.tool.inputReceived) {
      latestInputRef.current = context.tool.input as Input | undefined;
    }
  }, [context.tool.input, context.tool.inputReceived]);

  useEffect(() => {
    if (!hasExecutedRef.current) {
      setSnapshot(openingSnapshot(adapter, context.tool, mismatch));
    }
  }, [adapter, context.tool, mismatch]);

  const execute = useCallback(
    async function execute(input?: Input): Promise<ToolCallResult<Output>> {
      hasExecutedRef.current = true;
      if (arguments.length > 0) {
        hasExplicitInputRef.current = true;
        latestInputRef.current = input;
      }

      const request = ++latestRequestRef.current;
      if (mismatch !== undefined) {
        setSnapshot((current) => ({
          ...current,
          error: mismatch,
          isFetching: false,
          status: "error",
        }));
        return errorResult(mismatch);
      }

      setSnapshot((current) => ({
        ...current,
        error: undefined,
        isFetching: true,
        status: current.data === undefined ? "pending" : "success",
      }));
      const execution = await adapter.execute(latestInputRef.current, context.app);
      if (mountedRef.current && request === latestRequestRef.current) {
        setSnapshot((current) =>
          execution.callResult.error === undefined
            ? {
                data: execution.callResult.result,
                error: undefined,
                isFetching: false,
                rawResult: execution.rawResult ?? current.rawResult,
                status: "success",
              }
            : {
                data: current.data,
                error: execution.callResult.error,
                isFetching: false,
                rawResult: execution.rawResult ?? current.rawResult,
                status: "error",
              },
        );
      }
      return execution.callResult;
    },
    [adapter, context.app, mismatch],
  );

  return {
    data: snapshot.data,
    error: snapshot.error,
    execute,
    isError: snapshot.status === "error",
    isFetching: snapshot.isFetching,
    isLoading: snapshot.isFetching && snapshot.data === undefined,
    isSuccess: snapshot.status === "success",
    rawResult: snapshot.rawResult,
    status: snapshot.status,
  };
}
