import { useCallback, useRef, useState } from "react";
import type { App } from "@modelcontextprotocol/ext-apps";

import { useWidget } from "./widget-context";

export type ToolContract = {
  input: object;
  output: unknown;
};

type ToolRegistry<Tools> = {
  [Name in keyof Tools]: ToolContract;
};

type RequiredKeys<Input extends object> = {
  [Key in keyof Input]-?: object extends Pick<Input, Key> ? never : Key;
}[keyof Input];

type ToolCallArguments<Input extends object> = [keyof Input] extends [never]
  ? []
  : [RequiredKeys<Input>] extends [never]
    ? [input?: Input]
    : [input: Input];

type ToolCall<Contract extends ToolContract> = (
  ...args: ToolCallArguments<Contract["input"]>
) => Promise<Contract["output"]>;

export type UseToolResult<Contract extends ToolContract> = {
  call: ToolCall<Contract>;
  data: Contract["output"] | undefined;
  error: Error | undefined;
  loading: boolean;
};

type ToolApp = Pick<App, "callServerTool">;
type UseApp = () => ToolApp;

export function createUseTool<Tools extends ToolRegistry<Tools>>() {
  return createUseToolWithApp<Tools>(useWidget);
}

export function createUseToolWithApp<Tools extends ToolRegistry<Tools>>(useApp: UseApp) {
  return function useTool<Name extends Extract<keyof Tools, string>>(
    name: Name,
  ): UseToolResult<Tools[Name]> {
    const app = useApp();
    const [data, setData] = useState<Tools[Name]["output"]>();
    const [error, setError] = useState<Error>();
    const [loading, setLoading] = useState(false);
    const latestRequest = useRef(0);

    const call = useCallback(
      async (...args: unknown[]): Promise<Tools[Name]["output"]> => {
        const request = latestRequest.current + 1;
        latestRequest.current = request;
        setData(undefined);
        setError(undefined);
        setLoading(true);

        try {
          const input = args[0];
          const result = await app.callServerTool(
            input === undefined
              ? { name }
              : { name, arguments: input as Record<string, unknown> },
          );
          if (result.isError) {
            throw resultError(name, result);
          }
          const output = result.structuredContent as Tools[Name]["output"];
          if (latestRequest.current === request) {
            setData(output);
          }
          return output;
        } catch (cause: unknown) {
          const normalized = cause instanceof Error ? cause : new Error(String(cause));
          if (latestRequest.current === request) {
            setError(normalized);
          }
          throw normalized;
        } finally {
          if (latestRequest.current === request) {
            setLoading(false);
          }
        }
      },
      [app, name],
    ) as ToolCall<Tools[Name]>;

    return { call, data, error, loading };
  };
}

function resultError(
  name: string,
  result: Awaited<ReturnType<App["callServerTool"]>>,
): Error {
  const message = result.content
    .flatMap((content) => (content.type === "text" ? [content.text] : []))
    .join("\n");
  return new Error(message || `Tool ${JSON.stringify(name)} failed`);
}
