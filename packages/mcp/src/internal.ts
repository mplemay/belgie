import type { App } from "@modelcontextprotocol/ext-apps";
import { z } from "zod";

import type { RawToolResult, ToolCallResult } from "./tool-error";
import { TOOL_RESULT_SOURCE, createToolResultAdapter, errorResult, normalizeToolCallError } from "./tool-result-source";
import type { ToolResultSource } from "./tool-result-source";
import { getActiveWidget } from "./widget-context";

type GeneratedToolCall<Input extends object, Output> =
  Record<PropertyKey, never> extends Input
    ? (input?: Input, app?: App) => Promise<ToolCallResult<Output>>
    : (input: Input, app?: App) => Promise<ToolCallResult<Output>>;

type GeneratedTool<Input extends object, Output> = GeneratedToolCall<Input, Output> & ToolResultSource<Input, Output>;

type OutputSchema = Parameters<typeof z.fromJSONSchema>[0];

function createGeneratedToolCaller<Input extends object, Output>(
  name: string,
  success: (response: RawToolResult) => ToolCallResult<Output>,
): GeneratedTool<Input, Output> {
  const adapter = createToolResultAdapter<Input, Output>(name, success);
  const caller = async (input?: Input, explicitApp?: App): Promise<ToolCallResult<Output>> => {
    try {
      const app = explicitApp ?? getActiveWidget();
      return (await adapter.execute(input, app)).callResult;
    } catch (error: unknown) {
      return errorResult(normalizeToolCallError(error));
    }
  };
  Object.defineProperty(caller, TOOL_RESULT_SOURCE, { value: adapter });
  return caller as GeneratedTool<Input, Output>;
}

export function createGeneratedTool<Input extends object, Output>(
  name: string,
  outputSchema: OutputSchema,
): GeneratedTool<Input, Output> {
  const schema = z.fromJSONSchema(outputSchema) as z.ZodType<Output>;

  return createGeneratedToolCaller(name, (response) => {
    const parsed = schema.safeParse(response.structuredContent);
    if (!parsed.success) {
      return errorResult(parsed.error);
    }
    return { error: undefined, result: parsed.data };
  });
}

export function createGeneratedRawTool<Input extends object>(name: string): GeneratedTool<Input, RawToolResult> {
  return createGeneratedToolCaller(name, (response) => ({
    error: undefined,
    result: response,
  }));
}
