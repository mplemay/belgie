import { useCallback, useEffect, useRef, useState } from "react";

import type { App } from "@modelcontextprotocol/ext-apps";

import { getActiveWidget, useWidgetContext } from "./widget-context";

export type RawToolResult = Awaited<ReturnType<App["callServerTool"]>>;

export type ToolContract = {
  input: object;
  output: unknown;
};

export type ToolRegistry = Record<string, ToolContract>;

export type ToolResultMode = "raw" | "structured";

export type ToolCallOptions = {
  app?: App;
};

declare const TOOL_TYPES: unique symbol;

export type DefinedToolRegistry<Tools extends ToolRegistry> = Readonly<
  { [Name in keyof Tools]: ToolResultMode }
> & {
  readonly [TOOL_TYPES]?: Tools;
};

export type ToolName<Tools extends ToolRegistry> = Extract<keyof Tools, string>;

export type ToolInput<
  Tools extends ToolRegistry,
  Name extends ToolName<Tools>,
> = Tools[Name]["input"];

export type ToolOutput<
  Tools extends ToolRegistry,
  Name extends ToolName<Tools>,
> = Tools[Name]["output"];

export type UseToolStatus = "idle" | "pending" | "success" | "error";

type ToolArguments<
  Tools extends ToolRegistry,
  Name extends ToolName<Tools>,
> = {} extends ToolInput<Tools, Name>
  ? [input?: ToolInput<Tools, Name>, options?: ToolCallOptions]
  : [input: ToolInput<Tools, Name>, options?: ToolCallOptions];

export type CallTool<Tools extends ToolRegistry> = <Name extends ToolName<Tools>>(
  name: Name,
  ...args: ToolArguments<Tools, Name>
) => Promise<ToolOutput<Tools, Name>>;

export type UseToolResult<
  Tools extends ToolRegistry,
  Name extends ToolName<Tools>,
> = {
  data: ToolOutput<Tools, Name> | undefined;
  error: Error | null;
  status: UseToolStatus;
  isIdle: boolean;
  isLoading: boolean;
  isSuccess: boolean;
  isError: boolean;
  mutate: () => Promise<ToolOutput<Tools, Name>>;
};

export type UseTool<Tools extends ToolRegistry> = <Name extends ToolName<Tools>>(
  name: Name,
  ...args: ToolArguments<Tools, Name>
) => UseToolResult<Tools, Name>;

export function defineToolRegistry<Tools extends ToolRegistry>(
  modes: { [Name in keyof Tools]: ToolResultMode },
): DefinedToolRegistry<Tools> {
  return Object.freeze({ ...modes }) as DefinedToolRegistry<Tools>;
}

function toolError(result: RawToolResult): Error {
  const message = result.content
    .filter((content): content is { type: "text"; text: string } => {
      return content.type === "text";
    })
    .map((content) => content.text)
    .join("\n");
  return new Error(message || "The MCP tool returned an error");
}

async function executeTool<
  Tools extends ToolRegistry,
  Name extends ToolName<Tools>,
>(
  app: App,
  registry: DefinedToolRegistry<Tools>,
  name: Name,
  input: ToolInput<Tools, Name> | undefined,
): Promise<ToolOutput<Tools, Name>> {
  const response = await app.callServerTool({
    name,
    ...(input === undefined
      ? {}
      : { arguments: input as Record<string, unknown> }),
  });
  if (response.isError) {
    throw toolError(response);
  }

  if (registry[name] === "raw") {
    return response as ToolOutput<Tools, Name>;
  }
  if (
    !("structuredContent" in response) ||
    response.structuredContent === undefined
  ) {
    throw new Error(
      `MCP tool ${JSON.stringify(name)} declared an output schema but returned no structuredContent`,
    );
  }
  return response.structuredContent as ToolOutput<Tools, Name>;
}

export function createCallTool<Tools extends ToolRegistry>(
  registry: DefinedToolRegistry<Tools>,
): CallTool<Tools> {
  return async function callTool<Name extends ToolName<Tools>>(
    name: Name,
    ...args: ToolArguments<Tools, Name>
  ): Promise<ToolOutput<Tools, Name>> {
    const input = args[0] as ToolInput<Tools, Name> | undefined;
    const options = args[1] as ToolCallOptions | undefined;
    const app = options?.app ?? getActiveWidget();
    return executeTool(app, registry, name, input);
  };
}

export function createUseTool<Tools extends ToolRegistry>(
  registry: DefinedToolRegistry<Tools>,
): UseTool<Tools> {
  return function useTool<Name extends ToolName<Tools>>(
    name: Name,
    ...args: ToolArguments<Tools, Name>
  ): UseToolResult<Tools, Name> {
    const input = args[0] as ToolInput<Tools, Name> | undefined;
    const options = args[1] as ToolCallOptions | undefined;
    const contextApp = useWidgetContext();
    const app = options?.app ?? contextApp;
    if (app == null) {
      throw new Error("useTool must be used within a connected <Widget>");
    }
    const request = useRef<{
      name: Name;
      input: ToolInput<Tools, Name> | undefined;
    }>({ name, input });
    request.current = { name, input };
    const [data, setData] = useState<ToolOutput<Tools, Name>>();
    const [error, setError] = useState<Error | null>(null);
    const [status, setStatus] = useState<UseToolStatus>("idle");
    const mounted = useRef(false);
    const started = useRef(false);
    const latestCall = useRef(0);

    const mutate = useCallback(
      async () => {
        const { name: requestName, input: requestInput } = request.current;
        const callId = ++latestCall.current;
        if (mounted.current) {
          setData(undefined);
          setError(null);
          setStatus("pending");
        }

        try {
          const value = await executeTool(
            app,
            registry,
            requestName,
            requestInput,
          );

          if (mounted.current && latestCall.current === callId) {
            setData(value);
            setStatus("success");
          }
          return value;
        } catch (cause: unknown) {
          const nextError = cause instanceof Error ? cause : new Error(String(cause));
          if (mounted.current && latestCall.current === callId) {
            setError(nextError);
            setStatus("error");
          }
          throw nextError;
        }
      },
      [app, registry],
    );

    useEffect(() => {
      mounted.current = true;
      if (!started.current) {
        started.current = true;
        void mutate().catch(() => undefined);
      }
      return () => {
        mounted.current = false;
      };
    }, [mutate]);

    return {
      data,
      error,
      status,
      isIdle: status === "idle",
      isLoading: status === "pending",
      isSuccess: status === "success",
      isError: status === "error",
      mutate,
    };
  };
}
