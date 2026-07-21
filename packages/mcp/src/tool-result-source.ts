import type { App } from "@modelcontextprotocol/ext-apps";

import { McpToolError } from "./tool-error";
import type { McpToolErrorResult, RawToolResult, ToolCallError, ToolCallResult } from "./tool-error";

export const TOOL_RESULT_SOURCE: unique symbol = Symbol("belgie.tool-result-source");

export interface ToolResultExecution<Output> {
  callResult: ToolCallResult<Output>;
  rawResult: RawToolResult | undefined;
}

export interface ToolResultAdapter<Input extends object, Output> {
  name: string;
  execute: (input: Input | undefined, app: App) => Promise<ToolResultExecution<Output>>;
  parse: (response: RawToolResult) => ToolCallResult<Output>;
}

export interface ToolResultSource<Input extends object, Output> {
  readonly [TOOL_RESULT_SOURCE]: ToolResultAdapter<Input, Output>;
}

export function errorResult(error: ToolCallError): ToolCallResult<never> {
  return { error, result: undefined };
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
      return errorResult(new McpToolError(name, response as McpToolErrorResult));
    }
    return success(response);
  };

  return {
    async execute(input, app) {
      try {
        const rawResult = await app.callServerTool({
          name,
          ...(input === undefined ? {} : { arguments: input as Record<string, unknown> }),
        });
        return { callResult: parse(rawResult), rawResult };
      } catch (error: unknown) {
        return {
          callResult: errorResult(normalizeToolCallError(error)),
          rawResult: undefined,
        };
      }
    },
    name,
    parse,
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
