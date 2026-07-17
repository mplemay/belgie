import type { App } from "@modelcontextprotocol/ext-apps";
import { z } from "zod";

import { getActiveWidget } from "./widget-context";
import {
  McpToolError,
  type McpToolErrorResult,
  type RawToolResult,
  type ToolCallError,
  type ToolCallResult,
} from "./tool-error";

type GeneratedTool<Input extends object, Output> = {} extends Input
  ? (input?: Input, app?: App) => Promise<ToolCallResult<Output>>
  : (input: Input, app?: App) => Promise<ToolCallResult<Output>>;

type OutputSchema = Parameters<typeof z.fromJSONSchema>[0];

function errorResult(error: ToolCallError): ToolCallResult<never> {
  return { result: undefined, error };
}

function createGeneratedToolCaller<Input extends object, Output>(
  name: string,
  success: (response: RawToolResult) => ToolCallResult<Output>,
): GeneratedTool<Input, Output> {
  return (async (
    input?: Input,
    explicitApp?: App,
  ): Promise<ToolCallResult<Output>> => {
    try {
      const app = explicitApp ?? getActiveWidget();
      const response = await app.callServerTool({
        name,
        ...(input === undefined
          ? {}
          : { arguments: input as Record<string, unknown> }),
      });
      if (response.isError) {
        return errorResult(
          new McpToolError(name, response as McpToolErrorResult),
        );
      }
      return success(response);
    } catch (cause: unknown) {
      return errorResult(
        cause instanceof Error ? cause : new Error(String(cause)),
      );
    }
  }) as GeneratedTool<Input, Output>;
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
