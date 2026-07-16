import { useCallback, useEffect, useRef, useState } from "react";

import { useWidget } from "./widget-context";

export type RawToolResult = Awaited<ReturnType<ReturnType<typeof useWidget>["callServerTool"]>>;

export type ToolContract = {
  input: object;
  output: unknown;
};

export type ToolRegistry = Record<string, ToolContract>;

export type ToolResultMode = "raw" | "structured";

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
  ? [input?: ToolInput<Tools, Name>]
  : [input: ToolInput<Tools, Name>];

export type UseToolResult<
  Tools extends ToolRegistry,
  Name extends ToolName<Tools>,
> = {
  data: ToolOutput<Tools, Name> | undefined;
  error: Error | null;
  status: UseToolStatus;
  isIdle: boolean;
  isPending: boolean;
  isSuccess: boolean;
  isError: boolean;
  mutate: (...args: ToolArguments<Tools, Name>) => void;
  mutateAsync: (
    ...args: ToolArguments<Tools, Name>
  ) => Promise<ToolOutput<Tools, Name>>;
  reset: () => void;
};

export type UseTool<Tools extends ToolRegistry> = <Name extends ToolName<Tools>>(
  name: Name,
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

export function createUseTool<Tools extends ToolRegistry>(
  registry: DefinedToolRegistry<Tools>,
): UseTool<Tools> {
  return function useTool<Name extends ToolName<Tools>>(
    name: Name,
  ): UseToolResult<Tools, Name> {
    const app = useWidget();
    const [data, setData] = useState<ToolOutput<Tools, Name>>();
    const [error, setError] = useState<Error | null>(null);
    const [status, setStatus] = useState<UseToolStatus>("idle");
    const mounted = useRef(true);
    const latestCall = useRef(0);

    useEffect(() => {
      mounted.current = true;
      return () => {
        mounted.current = false;
      };
    }, []);

    const mutateAsync = useCallback(
      async (...args: [input?: ToolInput<Tools, Name>]) => {
        const input = args[0];
        const callId = ++latestCall.current;
        if (mounted.current) {
          setData(undefined);
          setError(null);
          setStatus("pending");
        }

        try {
          const response = await app.callServerTool({
            name,
            ...(input === undefined
              ? {}
              : { arguments: input as Record<string, unknown> }),
          });
          if (response.isError) {
            throw toolError(response);
          }

          const value = (() => {
            if (registry[name] === "raw") {
              return response;
            }
            if (
              !("structuredContent" in response) ||
              response.structuredContent === undefined
            ) {
              throw new Error(
                `MCP tool ${JSON.stringify(name)} declared an output schema but returned no structuredContent`,
              );
            }
            return response.structuredContent;
          })() as ToolOutput<Tools, Name>;

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
      [app, name, registry],
    );

    const mutate = useCallback(
      (...args: [input?: ToolInput<Tools, Name>]) => {
        void mutateAsync(...args).catch(() => undefined);
      },
      [mutateAsync],
    );

    const reset = useCallback(() => {
      latestCall.current += 1;
      if (mounted.current) {
        setData(undefined);
        setError(null);
        setStatus("idle");
      }
    }, []);

    return {
      data,
      error,
      status,
      isIdle: status === "idle",
      isPending: status === "pending",
      isSuccess: status === "success",
      isError: status === "error",
      mutate,
      mutateAsync,
      reset,
    };
  };
}
