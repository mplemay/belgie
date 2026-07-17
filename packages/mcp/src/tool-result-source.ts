import type { App } from "@modelcontextprotocol/ext-apps";

import {
  McpToolError,
  type McpToolErrorResult,
  type RawToolResult,
  type ToolCallError,
  type ToolCallResult,
} from "./tool-error";

export const TOOL_RESULT_SOURCE: unique symbol = Symbol(
  "belgie.tool-result-source",
);

export type ToolResultExecution<Output> = {
  callResult: ToolCallResult<Output>;
  rawResult: RawToolResult | undefined;
};

export type ToolResultAdapter<Input extends object, Output> = {
  name: string;
  execute: (
    input: Input | undefined,
    app: App,
  ) => Promise<ToolResultExecution<Output>>;
  parse: (response: RawToolResult) => ToolCallResult<Output>;
};

export type ToolResultSource<Input extends object, Output> = {
  readonly [TOOL_RESULT_SOURCE]: ToolResultAdapter<Input, Output>;
};

export function errorResult(error: ToolCallError): ToolCallResult<never> {
  return { result: undefined, error };
}

export function normalizeToolCallError(cause: unknown): ToolCallError {
  return cause instanceof Error ? cause : new Error(String(cause));
}

export function createToolResultAdapter<Input extends object, Output>(
  name: string,
  success: (response: RawToolResult) => ToolCallResult<Output>,
): ToolResultAdapter<Input, Output> {
  const parse = (response: RawToolResult): ToolCallResult<Output> => {
    if (response.isError) {
      return errorResult(
        new McpToolError(name, response as McpToolErrorResult),
      );
    }
    return success(response);
  };

  return {
    name,
    parse,
    async execute(input, app) {
      try {
        const rawResult = await app.callServerTool({
          name,
          ...(input === undefined
            ? {}
            : { arguments: input as Record<string, unknown> }),
        });
        return { callResult: parse(rawResult), rawResult };
      } catch (cause: unknown) {
        return {
          callResult: errorResult(normalizeToolCallError(cause)),
          rawResult: undefined,
        };
      }
    },
  };
}

export function getToolResultAdapter<Input extends object, Output>(
  source: ToolResultSource<Input, Output>,
): ToolResultAdapter<Input, Output> {
  const adapter = source[TOOL_RESULT_SOURCE];
  if (adapter === undefined) {
    throw new Error("useToolResult requires a generated MCP tool caller");
  }
  return adapter;
}
