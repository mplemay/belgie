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

export type UseToolState<
  Tools extends ToolRegistry,
  Name extends ToolName<Tools>,
> = {
  call: (
    ...args: {} extends ToolInput<Tools, Name>
      ? [input?: ToolInput<Tools, Name>]
      : [input: ToolInput<Tools, Name>]
  ) => Promise<ToolOutput<Tools, Name>>;
  result: ToolOutput<Tools, Name> | null;
  error: Error | null;
  loading: boolean;
  reset: () => void;
};

export type UseTool<Tools extends ToolRegistry> = <Name extends ToolName<Tools>>(
  name: Name,
) => UseToolState<Tools, Name>;

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
  ): UseToolState<Tools, Name> {
    const app = useWidget();
    const [result, setResult] = useState<ToolOutput<Tools, Name> | null>(null);
    const [error, setError] = useState<Error | null>(null);
    const [loading, setLoading] = useState(false);
    const mounted = useRef(true);
    const latestCall = useRef(0);

    useEffect(() => {
      mounted.current = true;
      return () => {
        mounted.current = false;
      };
    }, []);

    const call = useCallback(
      async (...args: [input?: ToolInput<Tools, Name>]) => {
        const callId = ++latestCall.current;
        if (mounted.current) {
          setResult(null);
          setError(null);
          setLoading(true);
        }

        try {
          const input = args[0];
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
            setResult(value);
            setLoading(false);
          }
          return value;
        } catch (cause: unknown) {
          const nextError = cause instanceof Error ? cause : new Error(String(cause));
          if (mounted.current && latestCall.current === callId) {
            setError(nextError);
            setLoading(false);
          }
          throw nextError;
        }
      },
      [app, name, registry],
    );

    const reset = useCallback(() => {
      latestCall.current += 1;
      if (mounted.current) {
        setResult(null);
        setError(null);
        setLoading(false);
      }
    }, []);

    return {
      call: call as UseToolState<Tools, Name>["call"],
      result,
      error,
      loading,
      reset,
    };
  };
}
