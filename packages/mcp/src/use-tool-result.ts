import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  McpToolCancelledError,
  type RawToolResult,
  type ToolCallError,
  type ToolCallResult,
} from "./tool-error";
import {
  errorResult,
  getToolResultAdapter,
  type ToolResultAdapter,
  type ToolResultSource,
} from "./tool-result-source";
import {
  useConnectedWidgetContext,
  type WidgetContextValue,
  type WidgetToolLifecycle,
} from "./widget-context";

export type ToolResultStatus = "pending" | "success" | "error";

export type ToolResultState<Input extends object, Output> = {
  data: Output | undefined;
  error: ToolCallError | undefined;
  rawResult: RawToolResult | undefined;
  status: ToolResultStatus;
  isLoading: boolean;
  isFetching: boolean;
  isSuccess: boolean;
  isError: boolean;
  execute: (input?: Input) => Promise<ToolCallResult<Output>>;
};

type ResultSnapshot<Output> = {
  data: Output | undefined;
  error: ToolCallError | undefined;
  rawResult: RawToolResult | undefined;
  status: ToolResultStatus;
  isFetching: boolean;
};

function sourceMismatchError<Input extends object, Output>(
  adapter: ToolResultAdapter<Input, Output>,
  context: WidgetContextValue,
): Error | undefined {
  const actualName = context.app.getHostContext()?.toolInfo?.tool.name;
  if (actualName === undefined || actualName === adapter.name) {
    return undefined;
  }
  return new Error(
    `useToolResult expected opening tool ${JSON.stringify(adapter.name)}, received ${JSON.stringify(actualName)}`,
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
      rawResult: lifecycle.rawResult,
      status: "error",
      isFetching: false,
    };
  }
  if (lifecycle.status === "pending") {
    return {
      data: undefined,
      error: undefined,
      rawResult: undefined,
      status: "pending",
      isFetching: true,
    };
  }
  if (lifecycle.status === "cancelled") {
    return {
      data: undefined,
      error: new McpToolCancelledError(
        adapter.name,
        lifecycle.cancellationReason,
      ),
      rawResult: undefined,
      status: "error",
      isFetching: false,
    };
  }

  const rawResult = lifecycle.rawResult!;
  const callResult = adapter.parse(rawResult);
  return callResult.error === undefined
    ? {
        data: callResult.result,
        error: undefined,
        rawResult,
        status: "success",
        isFetching: false,
      }
    : {
        data: undefined,
        error: callResult.error,
        rawResult,
        status: "error",
        isFetching: false,
      };
}

export function useToolResult<Input extends object, Output>(
  source: ToolResultSource<Input, Output>,
): ToolResultState<Input, Output> {
  const context = useConnectedWidgetContext("useToolResult");
  const adapter = getToolResultAdapter(source);
  const mismatch = useMemo(
    () => sourceMismatchError(adapter, context),
    [adapter, context.app],
  );
  const [snapshot, setSnapshot] = useState<ResultSnapshot<Output>>(() =>
    openingSnapshot(adapter, context.tool, mismatch),
  );
  const hasExecutedRef = useRef(false);
  const latestInputRef = useRef<Input | undefined>(
    context.tool.input as Input | undefined,
  );
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
    if (!hasExecutedRef.current && context.tool.inputReceived) {
      latestInputRef.current = context.tool.input as Input | undefined;
    }
  }, [context.tool.input, context.tool.inputReceived]);

  useEffect(() => {
    if (!hasExecutedRef.current) {
      setSnapshot(openingSnapshot(adapter, context.tool, mismatch));
    }
  }, [adapter, context.tool, mismatch]);

  const execute = useCallback(
    async (input?: Input): Promise<ToolCallResult<Output>> => {
      hasExecutedRef.current = true;
      if (input !== undefined) {
        latestInputRef.current = input;
      }

      const request = ++latestRequestRef.current;
      if (mismatch !== undefined) {
        setSnapshot((current) => ({
          ...current,
          error: mismatch,
          status: "error",
          isFetching: false,
        }));
        return errorResult(mismatch);
      }

      setSnapshot((current) => ({
        ...current,
        error: undefined,
        status: current.data === undefined ? "pending" : "success",
        isFetching: true,
      }));
      const execution = await adapter.execute(
        latestInputRef.current,
        context.app,
      );
      if (mountedRef.current && request === latestRequestRef.current) {
        setSnapshot((current) =>
          execution.callResult.error === undefined
            ? {
                data: execution.callResult.result,
                error: undefined,
                rawResult: execution.rawResult ?? current.rawResult,
                status: "success",
                isFetching: false,
              }
            : {
                data: current.data,
                error: execution.callResult.error,
                rawResult: execution.rawResult ?? current.rawResult,
                status: "error",
                isFetching: false,
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
    rawResult: snapshot.rawResult,
    status: snapshot.status,
    isLoading: snapshot.isFetching && snapshot.data === undefined,
    isFetching: snapshot.isFetching,
    isSuccess: snapshot.status === "success",
    isError: snapshot.status === "error",
    execute,
  };
}
