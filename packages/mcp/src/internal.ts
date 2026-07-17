import type { App } from "@modelcontextprotocol/ext-apps";
import { z } from "zod";

import { getActiveWidget } from "./widget-context";
import {
  type RawToolResult,
  type ToolCallResult,
} from "./tool-error";
import {
  TOOL_RESULT_SOURCE,
  createToolResultAdapter,
  errorResult,
  normalizeToolCallError,
  type ToolResultSource,
} from "./tool-result-source";

type GeneratedToolCall<Input extends object, Output> = {} extends Input
  ? (input?: Input, app?: App) => Promise<ToolCallResult<Output>>
  : (input: Input, app?: App) => Promise<ToolCallResult<Output>>;

type GeneratedTool<Input extends object, Output> = GeneratedToolCall<
  Input,
  Output
> &
  ToolResultSource<Input, Output>;

type OutputSchema = Parameters<typeof z.fromJSONSchema>[0];

function createGeneratedToolCaller<Input extends object, Output>(
  name: string,
  success: (response: RawToolResult) => ToolCallResult<Output>,
): GeneratedTool<Input, Output> {
  const adapter = createToolResultAdapter<Input, Output>(name, success);
  const caller = async (
    input?: Input,
    explicitApp?: App,
  ): Promise<ToolCallResult<Output>> => {
    try {
      const app = explicitApp ?? getActiveWidget();
      return (await adapter.execute(input, app)).callResult;
    } catch (cause: unknown) {
      return errorResult(normalizeToolCallError(cause));
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
    return { result: parsed.data, error: undefined };
  });
}

export function createGeneratedRawTool<Input extends object>(
  name: string,
): GeneratedTool<Input, RawToolResult> {
  return createGeneratedToolCaller(name, (response) => ({
    result: response,
    error: undefined,
  }));
}
